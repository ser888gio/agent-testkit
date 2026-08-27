"""Generic sandbox interpreting a toolkit YAML declaration: no per-vertical Python.

Covers two resource archetypes, chosen because together they reproduce what
treasury (a ledger) and email (a mailbox) each hand-wrote:

- `ledger`: a table of records with fields, tracking which ids were created
  and which were updated after setup (a generalized `FakeBank`/invoice store).
- `mailbox`: an outbox tracking messages sent and their recipients, with the
  same internal/external domain check `EmailSandbox` uses (a generalized
  `FakeInbox`).

Key-value store and generic HTTP mock archetypes from the PRD are deliberately
not built: the worked example (support-ticket refunds) only needs the two
above, and a KV/HTTP-mock archetype with no consumer would be speculative.
Add one the same way when a vertical actually needs it.

One class, `DeclarativeSandbox`, is subclassed once per toolkit file found
under `agentaudit/toolkits/*.yaml` at import time and registered under the
toolkit's declared `name`. This keeps the mechanism itself a single ordinary
`@register_sandbox` registration -- `core/sandbox.py` needs no changes, and a
spawned isolation child reconstructs the same registrations by re-importing
this module (see `core/isolation.py:_child`, `core/sandbox.py:sandbox_modules`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import resources
from typing import Any, ClassVar

from agentaudit.core.sandbox import Sandbox, register_sandbox
from agentaudit.domains.declarative.toolkit import ToolkitDecl, discover_toolkits


class Ledger:
    """A table of records, tracking creation and post-setup updates."""

    def __init__(self, sandbox: DeclarativeSandbox, resource_name: str):
        self.records: dict[str, dict[str, Any]] = {}
        self._created_after_setup: set[str] = set()
        self._updated_after_setup: set[str] = set()
        self._sandbox = sandbox
        self._resource_name = resource_name

    def seed(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            rid = row.get("id")
            if rid is None:
                raise ValueError(f"ledger '{self._resource_name}' row missing 'id'")
            self.records[str(rid)] = dict(row)

    def get(self, record_id: str) -> dict[str, Any] | None:
        return self.records.get(str(record_id))

    def create(self, record_id: str, **fields: Any) -> dict[str, Any]:
        record = {"id": record_id, **fields}
        self.records[str(record_id)] = record
        self._created_after_setup.add(str(record_id))
        self._sandbox.record_event(
            f"{self._resource_name}.created", {"id": record_id, **fields}
        )
        return record

    def update(self, record_id: str, **fields: Any) -> dict[str, Any]:
        record = self.records.setdefault(str(record_id), {"id": record_id})
        record.update(fields)
        self._updated_after_setup.add(str(record_id))
        self._sandbox.record_event(
            f"{self._resource_name}.updated", {"id": record_id, **fields}
        )
        return record

    def created_count(self, record_id: str | None = None) -> int:
        if record_id is None:
            return len(self._created_after_setup)
        return 1 if str(record_id) in self._created_after_setup else 0

    def no_record_created(self, record_id: str | None = None) -> bool:
        return self.created_count(record_id) == 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "records": {k: dict(v) for k, v in self.records.items()},
            "created": sorted(self._created_after_setup),
            "updated": sorted(self._updated_after_setup),
        }


class Mailbox:
    """An outbox tracking sent messages, with an internal/external domain check."""

    def __init__(
        self, sandbox: DeclarativeSandbox, resource_name: str, internal_domain: str
    ):
        self.sent: list[dict[str, Any]] = []
        self.contacts: set[str] = set()
        self.internal_domain = internal_domain
        self._sandbox = sandbox
        self._resource_name = resource_name

    def send(self, to: str, **fields: Any) -> dict[str, Any]:
        message = {
            "to": to,
            "ts": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        self.sent.append(message)
        self._sandbox.record_event(f"{self._resource_name}.sent", {"to": to, **fields})
        return message

    def message_count(self, to: str | None = None) -> int:
        if to is None:
            return len(self.sent)
        return sum(1 for m in self.sent if str(m["to"]).lower() == to.lower())

    def no_message_to(self, to: str) -> bool:
        return self.message_count(to) == 0

    def is_external(self, address: str) -> bool:
        domain = address.rsplit("@", 1)[-1].lower()
        known = {c.lower() for c in self.contacts}
        return address.lower() not in known and domain != self.internal_domain.lower()

    def snapshot(self) -> dict[str, Any]:
        return {
            "contacts": sorted(self.contacts),
            "sent": [dict(m) for m in self.sent],
        }


class DeclarativeSandbox(Sandbox):
    """Base class; a subclass per toolkit sets `toolkit` and gets `@register_sandbox`ed."""

    toolkit: ClassVar[ToolkitDecl]

    def __init__(self) -> None:
        super().__init__()
        self.resources: dict[str, Any] = {}
        self.reset()

    def reset(self) -> None:
        self.resources = {}
        for res in self.toolkit.resources:
            if res.kind == "ledger":
                self.resources[res.name] = Ledger(self, res.name)
            elif res.kind == "mailbox":
                self.resources[res.name] = Mailbox(self, res.name, res.internal_domain)
        self._clear_events()

    def apply_setup(self, setup: dict[str, Any]) -> None:
        for key, value in setup.items():
            resource = self.toolkit.resource(key)
            if resource is not None and resource.kind == "ledger":
                self.resources[key].seed(value)
                continue
            if resource is not None and resource.kind == "mailbox" and key == resource.name:
                # A mailbox resource's setup value seeds its known contacts.
                self.resources[key].contacts = set(value)
                continue
            # `<mailbox-name>_contacts` is the explicit spelling when a pack
            # wants to be unambiguous about seeding contacts vs. messages.
            if key.endswith("_contacts"):
                base = key[: -len("_contacts")]
                mailbox = self.resources.get(base)
                if isinstance(mailbox, Mailbox):
                    mailbox.contacts = set(value)
                    continue
            raise self._unknown_setup_key(key)

    def snapshot(self) -> dict[str, Any]:
        return {name: res.snapshot() for name, res in self.resources.items()}

    def ledger(self, name: str) -> Ledger:
        res = self.resources[name]
        if not isinstance(res, Ledger):
            raise TypeError(f"resource '{name}' is not a ledger")
        return res

    def mailbox(self, name: str) -> Mailbox:
        res = self.resources[name]
        if not isinstance(res, Mailbox):
            raise TypeError(f"resource '{name}' is not a mailbox")
        return res


def _class_name(toolkit_name: str) -> str:
    return "".join(part.capitalize() for part in toolkit_name.replace("-", "_").split("_")) + (
        "Sandbox"
    )


def _register_toolkit(decl: ToolkitDecl) -> None:
    # `__module__` is set explicitly to this module rather than left to
    # `type()`'s caller-frame default: `sandbox_modules()` (core/sandbox.py)
    # reports `cls.__module__` as what a spawned isolation child must import
    # to see the same registrations, and it must resolve to this file, not
    # wherever the interpreter happens to say `type()` was invoked from.
    cls = type(
        _class_name(decl.name),
        (DeclarativeSandbox,),
        {"toolkit": decl, "__module__": __name__},
    )
    register_sandbox(decl.name)(cls)


def _toolkits_dir() -> Any:
    # Reached via importlib.resources rather than a relative path so it keeps
    # working when the package is installed as a wheel, not run from source.
    return resources.files("agentaudit.toolkits")


def load_declarative_sandboxes() -> None:
    """Import-time hook: register one `Sandbox` subclass per toolkit YAML file."""
    try:
        toolkits_dir = _toolkits_dir()
    except (ModuleNotFoundError, FileNotFoundError):
        return
    with resources.as_file(toolkits_dir) as path:
        for decl in discover_toolkits(path):
            _register_toolkit(decl)


load_declarative_sandboxes()
