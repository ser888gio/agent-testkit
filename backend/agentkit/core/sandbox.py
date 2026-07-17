"""Generic sandbox interface: state seeding, side-effect events, snapshots/diffs.

Domain-agnostic on purpose — treasury/email sandboxes plug into this without
this module knowing anything about payments or mail.
"""

from __future__ import annotations

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


def register_sandbox(name: str):
    def _decorator(cls: type[Sandbox]) -> type[Sandbox]:
        cls.name = name
        SANDBOXES[name] = cls
        return cls

    return _decorator


def build_sandbox(name: str) -> Sandbox:
    try:
        cls = SANDBOXES[name]
    except KeyError:
        valid = ", ".join(sorted(SANDBOXES)) or "(none registered)"
        raise KeyError(
            f"unknown sandbox '{name}'; registered sandboxes: {valid}"
        ) from None
    return cls()
