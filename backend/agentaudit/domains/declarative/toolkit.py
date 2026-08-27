"""Toolkit YAML loading: turns a declaration file into a validated dict.

A toolkit declares a vertical's fake resources without any Python. Kept
separate from `sandbox.py` so parsing/validation has one place to live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TOOLKITS_PACKAGE = "agentaudit.toolkits"
SUPPORTED_KINDS = ("ledger", "mailbox")


class ToolkitError(Exception):
    pass


@dataclass(frozen=True)
class ResourceDecl:
    kind: str
    name: str
    # ledger: field names a record may carry (informational; any field is
    # accepted at setup time, this only documents intent).
    fields: list[str] = field(default_factory=list)
    # mailbox: the domain treated as "not external".
    internal_domain: str = "acme.example"


@dataclass(frozen=True)
class ToolkitDecl:
    name: str
    resources: list[ResourceDecl]
    source: Path

    def resource(self, name: str) -> ResourceDecl | None:
        return next((r for r in self.resources if r.name == name), None)

    def resources_of_kind(self, kind: str) -> list[ResourceDecl]:
        return [r for r in self.resources if r.kind == kind]


def _build_resource(raw: dict[str, Any], source: Path) -> ResourceDecl:
    if not isinstance(raw, dict):
        raise ToolkitError(f"{source}: each resource must be a mapping")
    kind = raw.get("kind")
    name = raw.get("name")
    if kind not in SUPPORTED_KINDS:
        raise ToolkitError(
            f"{source}: unsupported resource kind '{kind}' "
            f"(supported: {', '.join(SUPPORTED_KINDS)})"
        )
    if not name or not isinstance(name, str):
        raise ToolkitError(f"{source}: resource of kind '{kind}' is missing a 'name'")
    return ResourceDecl(
        kind=kind,
        name=name,
        fields=list(raw.get("fields", [])),
        internal_domain=raw.get("internal_domain", "acme.example"),
    )


def load_toolkit_file(path: str | Path) -> ToolkitDecl:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ToolkitError(f"{path}: expected a mapping")

    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ToolkitError(f"{path}: toolkit is missing a top-level 'name'")

    resources_raw = raw.get("resources") or []
    if not isinstance(resources_raw, list) or not resources_raw:
        raise ToolkitError(f"{path}: toolkit '{name}' must declare at least one resource")

    resources = [_build_resource(r, path) for r in resources_raw]
    names = [r.name for r in resources]
    if len(names) != len(set(names)):
        raise ToolkitError(f"{path}: resource names must be unique within a toolkit")

    return ToolkitDecl(name=name, resources=resources, source=path)


def discover_toolkits(root: str | Path) -> list[ToolkitDecl]:
    """Every `*.yaml` toolkit declaration under `root`, sorted by file name."""
    root = Path(root)
    if not root.is_dir():
        return []
    paths = sorted(p for p in root.glob("*.yaml"))
    return [load_toolkit_file(p) for p in paths]
