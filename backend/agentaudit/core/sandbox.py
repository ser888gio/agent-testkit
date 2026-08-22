"""Generic sandbox interface: state seeding, side-effect events, snapshots/diffs.

Domain-agnostic on purpose — treasury/email sandboxes plug into this without
this module knowing anything about payments or mail.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Event:
    kind: str
    data: dict[str, Any]
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Sandbox(ABC):
    name: str = ""

    def __init__(self) -> None:
        self._events: list[Event] = []

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def record_event(self, kind: str, data: dict[str, Any]) -> None:
        self._events.append(Event(kind=kind, data=data))

    def _clear_events(self) -> None:
        self._events.clear()

    @abstractmethod
    def reset(self) -> None:
        """Return the sandbox to a clean, deterministic zero-state (clears events)."""

    @abstractmethod
    def apply_setup(self, setup: dict[str, Any]) -> None:
        """Seed state from TestCase.setup. Unknown keys must raise ValueError."""

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Deep, JSON-serializable state snapshot."""

    def diff(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        added: dict[str, Any] = {}
        removed: dict[str, Any] = {}
        changed: dict[str, Any] = {}

        for key, after_val in after.items():
            if key not in before:
                added[key] = after_val
            elif before[key] != after_val:
                changed[key] = {"before": before[key], "after": after_val}

        for key, before_val in before.items():
            if key not in after:
                removed[key] = before_val

        return {"added": added, "removed": removed, "changed": changed}

    def _unknown_setup_key(self, key: str) -> ValueError:
        return ValueError(f"sandbox '{self.name}' cannot apply setup key '{key}'")


SANDBOXES: dict[str, type[Sandbox]] = {}

# Registration happens by import side-effect, so the registry performs that
# import itself rather than trusting seven call sites to remember it. Named as
# a string and imported on demand, never at module scope: `core` must not carry
# a dependency edge to `domains`. The package lists its own verticals, so a new
# built-in one still needs no change here. Third-party sandboxes are unaffected
# -- they register by being imported, exactly as before.
BUILTIN_SANDBOX_PACKAGE = "agentaudit.domains"


def load_builtin_sandboxes() -> None:
    """Import the built-in verticals so `SANDBOXES` is complete. Idempotent."""
    importlib.import_module(BUILTIN_SANDBOX_PACKAGE)


def sandbox_modules() -> tuple[str, ...]:
    """The modules a fresh interpreter must import to see this registry.

    Asked of the registry rather than inferred from `sys.modules`, so a spawned
    child gets what is actually registered instead of whatever the parent
    happened to import.
    """
    load_builtin_sandboxes()
    return tuple(sorted({cls.__module__ for cls in SANDBOXES.values()}))


def register_sandbox(name: str):
    def _decorator(cls: type[Sandbox]) -> type[Sandbox]:
        cls.name = name
        SANDBOXES[name] = cls
        return cls

    return _decorator


def build_sandbox(name: str) -> Sandbox:
    load_builtin_sandboxes()
    try:
        cls = SANDBOXES[name]
    except KeyError:
        valid = ", ".join(sorted(SANDBOXES)) or "(none registered)"
        raise KeyError(
            f"unknown sandbox '{name}'; registered sandboxes: {valid}"
        ) from None
    return cls()
