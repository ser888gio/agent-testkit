"""Where the attacker and judge models are configured, and how their keys are found.

Three modules used to answer this independently. `attacker.py`, `judge.py` and
`evolve.py` each read `AGENTAUDIT_*_ENDPOINT`/`_MODEL`/`_API_KEY` out of
`os.environ` and each built its own `HTTPAttacker`. Same six variables, three
spellings, and no way to see the whole LLM configuration in one place -- which
is what a settings page needs and what an operator asks for first.

One file now describes both roles, and `build_attacker`/`build_judge`/
`build_generator` read it.

## Where the key lives

The config file holds an `api_key_ref` -- `env://OPENAI_API_KEY` -- never a key.
That is not a style preference, it is the rule the rest of this repo already
enforces:

- `store.py:save_target` refuses to persist a config containing a credential
  literal, and requires an opaque `scheme://` reference instead.
- `worker.py:resolve_secret` resolves that reference from the *worker's*
  environment, scoped to one run, without mutating `os.environ`.
- `credentials.py` owns the shared vocabulary for both.

So a config file is safe to commit, diff, and mount as a ConfigMap; the key is
supplied the way the deployment already supplies every other secret (env var,
Docker secret, or a k8s Secret projected into the environment). It is the same
reasoning the attacker docstring gives for never reading the key out of a
target file, applied one level up.

`api_key_env` is accepted as a bare variable name for the same thing, because
`OPENAI_API_KEY` is what the OpenAI SDK itself reads and making an operator
write `env://OPENAI_API_KEY` to say so is friction with no security gain.

## Why not the OpenAI SDK

`HTTPAttacker` speaks the OpenAI chat-completions wire format over `httpx`,
which is already a dependency. Adding `openai` would buy retries and typed
responses for a single POST whose failure mode is deliberately "fall back to
the scripted ladder", and would breach the rule that `httpx` is imported in
exactly one module (`core/agent.py`) so the network surface stays auditable.
Any OpenAI-compatible endpoint -- OpenAI, Azure, vLLM, Ollama, LiteLLM,
Anthropic behind a proxy -- works against the client that is already here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from agentaudit.core import credentials

DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"

# Checked in order; the first that exists wins. `AGENTAUDIT_LLM_CONFIG` lets a
# deployment point at a mounted file without depending on the working directory.
_SEARCH_PATHS = ("agentaudit/llm.yaml", ".agentaudit/llm.yaml")


class LLMConfigError(Exception):
    pass


class RoleConfig(BaseModel):
    """One model role. `endpoint` defaults to OpenAI; any compatible host works."""

    model: str
    endpoint: str = DEFAULT_ENDPOINT
    api_key_ref: str | None = None
    timeout_s: float = 30.0
    temperature: float | None = None

    def api_key(self) -> str | None:
        """Resolve `api_key_ref` from the process environment.

        Returns None rather than raising when the variable is unset: an
        unauthenticated local endpoint (Ollama, vLLM) is a legitimate setup, and
        a wrong-or-missing key surfaces as `AttackerUnavailable` at call time,
        which every caller already falls back from.
        """
        name = _env_name(self.api_key_ref)
        return os.environ.get(name) if name else None


class LLMConfig(BaseModel):
    """The attacker and judge model configuration.

    Both roles are optional: an absent role leaves that capability off, which is
    the same default as an unset env var and keeps CI offline and deterministic.
    """

    attacker: RoleConfig | None = None
    judge: RoleConfig | None = None


def _env_name(ref: str | None) -> str | None:
    """The variable name behind `env://VAR`, `${VAR}`, or a bare `VAR`."""
    if not ref:
        return None
    ref = ref.strip()
    scheme, sep, remainder = ref.partition("://")
    if sep:
        if scheme.lower() != "env":
            raise LLMConfigError(f"unsupported api_key_ref scheme '{scheme}://'")
        return remainder.strip() or None
    if ref.startswith("${") and ref.endswith("}"):
        return ref[2:-1].strip() or None
    return ref


def load_llm_dict(raw: Any, source: str = "<dict>") -> LLMConfig:
    """Validate an already-parsed LLM config mapping."""
    if raw is None:
        return LLMConfig()
    if not isinstance(raw, dict):
        raise LLMConfigError(f"llm config at {source} must be a mapping, got {type(raw).__name__}")

    # A pasted key is the failure this whole design exists to prevent, so it is
    # refused at the door rather than quietly used -- the same call and the same
    # answer `store.save_target` gives a target config.
    for role, section in raw.items():
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            if isinstance(value, str) and credentials.looks_like_secret(value):
                raise LLMConfigError(
                    f"llm config at {source} has a credential literal in {role}.{key}; "
                    "use api_key_ref: env://YOUR_VAR and supply the key in the environment"
                )

    try:
        config = LLMConfig.model_validate(raw)
    except ValidationError as exc:
        raise LLMConfigError(f"invalid llm config at {source}: {exc}") from exc

    # Surface an unsupported scheme now, not at the first attack turn.
    for role in (config.attacker, config.judge):
        if role is not None:
            _env_name(role.api_key_ref)
    return config


def config_path() -> Path | None:
    """The LLM config file in effect, or None when there is none."""
    override = os.environ.get("AGENTAUDIT_LLM_CONFIG")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    for candidate in _SEARCH_PATHS:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def load_llm_config(path: str | Path | None = None) -> LLMConfig:
    """Load the LLM config, falling back to the legacy environment variables.

    An empty config is a valid answer -- it means both roles are off -- so a
    missing file is not an error. The env-var path stays supported because it is
    what every existing deployment, CI job and docstring in this repo uses.
    """
    resolved = Path(path) if path is not None else config_path()
    if resolved is None:
        return _from_env()
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LLMConfigError(f"malformed llm config at {resolved}: {exc}") from exc
    return load_llm_dict(raw, source=str(resolved))


def _from_env() -> LLMConfig:
    """The pre-config-file variables, so existing deployments keep working."""

    def role(prefix: str) -> RoleConfig | None:
        endpoint = os.environ.get(f"AGENTAUDIT_{prefix}_ENDPOINT")
        model = os.environ.get(f"AGENTAUDIT_{prefix}_MODEL")
        if not endpoint or not model:
            return None
        return RoleConfig(
            model=model,
            endpoint=endpoint,
            api_key_ref=f"env://AGENTAUDIT_{prefix}_API_KEY",
        )

    return LLMConfig(attacker=role("ATTACKER"), judge=role("JUDGE"))


def build_client(role: RoleConfig | None, default_temperature: float) -> Any | None:
    """An `HTTPAttacker` for a role, or None when the role is unconfigured.

    Imported here rather than at module scope to keep `httpx` -- which
    `core/agent.py` alone imports -- off this module's import path.
    """
    if role is None:
        return None
    from agentaudit.core.agent import HTTPAttacker

    temperature = role.temperature if role.temperature is not None else default_temperature
    return HTTPAttacker(
        endpoint=role.endpoint,
        model=role.model,
        api_key=role.api_key(),
        timeout_s=role.timeout_s,
        temperature=temperature,
    )


def describe() -> dict[str, Any]:
    """The LLM configuration as the settings view shows it -- never the key.

    Reports whether each role is configured and whether its key resolves, so an
    operator can tell "no model" from "model, but the key is not provisioned on
    this worker" without the value ever leaving the process.
    """
    try:
        config = load_llm_config()
        error = None
    except LLMConfigError as exc:
        config, error = LLMConfig(), str(exc)

    path = config_path()
    configured = config.attacker is not None or config.judge is not None
    source = str(path) if path else ("environment" if configured else None)

    def role(spec: RoleConfig | None) -> dict[str, Any]:
        if spec is None:
            return {"configured": False}
        name = _env_name(spec.api_key_ref)
        return {
            "configured": True,
            "model": spec.model,
            "endpoint": spec.endpoint,
            "api_key_env": name,
            "api_key_present": bool(name and os.environ.get(name)),
        }

    return {
        "source": source,
        "error": error,
        "attacker": role(config.attacker),
        "judge": role(config.judge),
    }
