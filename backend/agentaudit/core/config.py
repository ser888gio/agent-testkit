"""Target configuration: how to reach an agent, which sandbox, and evidence policy."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from agentaudit.core.redaction import EvidencePolicy

KNOWN_SANDBOXES = ("treasury", "email")

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    pass


class ResponseSpec(BaseModel):
    text_path: str = "$.text"


class CallableSpec(BaseModel):
    type: Literal["callable"]
    callable: str


class HTTPSpec(BaseModel):
    type: Literal["http"]
    endpoint: str
    method: Literal["POST", "GET"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    request: dict[str, Any] = Field(default_factory=dict)
    response: ResponseSpec = Field(default_factory=ResponseSpec)
    timeout_s: float = 30.0


AgentSpec = Annotated[CallableSpec | HTTPSpec, Field(discriminator="type")]


class TargetConfig(BaseModel):
    id: str
    agent: AgentSpec
    sandbox: str | None = None
    evidence: EvidencePolicy = Field(default_factory=EvidencePolicy)


def _interpolate_env(value: Any, config_id: str, secrets: Mapping[str, str]) -> Any:
    if isinstance(value, str):

        def _sub(match: re.Match[str]) -> str:
            var = match.group(1)
            if var not in secrets:
                raise ConfigError(
                    f"env var {var} referenced by config '{config_id}' is unset"
                )
            return secrets[var]

        return _ENV_VAR_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v, config_id, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v, config_id, secrets) for v in value]
    return value


def load_target_dict(
    raw: Any,
    source: str = "<dict>",
    secrets: Mapping[str, str] | None = None,
) -> TargetConfig:
    """Validate an already-parsed target mapping. `source` names it in errors.

    `secrets` supplies the values for `${VAR}` references. Passing an explicit
    mapping is how a worker scopes a resolved credential to one run: nothing
    mutates `os.environ`, so a concurrent run in another thread cannot read it.
    `None` keeps the process environment, which is the CLI's single-tenant path.
    """
    if not isinstance(raw, dict):
        raise ConfigError(
            f"config at {source} must be a mapping, got {type(raw).__name__}"
        )

    config_id = raw.get("id", source)
    raw = _interpolate_env(raw, config_id, os.environ if secrets is None else secrets)

    sandbox = raw.get("sandbox")
    if sandbox is not None and sandbox not in KNOWN_SANDBOXES:
        raise ConfigError(
            f"unknown sandbox '{sandbox}' for config '{config_id}'; "
            f"valid sandboxes: {', '.join(KNOWN_SANDBOXES)}"
        )

    agent = raw.get("agent") or {}
    if not isinstance(agent, dict):
        raise ConfigError(
            f"agent for config '{config_id}' must be a mapping, got {type(agent).__name__}"
        )
    if agent.get("type") == "http" and not agent.get("endpoint"):
        raise ConfigError(f"http target '{config_id}' requires endpoint")

    try:
        return TargetConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid config '{config_id}': {exc}") from exc


def load_target(path: str | Path, secrets: Mapping[str, str] | None = None) -> TargetConfig:
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    try:
        if path.suffix == ".json":
            raw = json.loads(text)
        else:
            raw = yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ConfigError(f"malformed config at {path}: {exc}") from exc

    return load_target_dict(raw, source=str(path), secrets=secrets)
