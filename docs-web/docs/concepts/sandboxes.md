---
id: sandboxes
title: Sandboxes
sidebar_position: 3
---

# Sandboxes

A sandbox is the fake world you put around the agent. It holds state, records
what the agent did to it, and lets assertions check the outcome instead of the
prose.

## Why they exist

Without a sandbox, the strongest claim you can make is "the reply did not
contain the word PWNED". With one, you can make the claim that matters:

> No payment row was created for invoice INV-100.

That claim holds even if the agent wrote a convincing refusal and then called
the payment tool anyway.

## The lifecycle

For every test, the runner does the same four things:

1. **Reset.** The sandbox returns to a clean, deterministic zero state. Tests
   never leak state into each other.
2. **Apply setup.** The test's `setup:` block seeds state — invoices, mailboxes,
   limits. An unknown setup key is an error, not a silent no-op.
3. **Snapshot before.** A JSON-serializable picture of the state.
4. **Run, then snapshot after.** The difference between the two snapshots is the
   evidence you see in the report.

Assertions run against the state after the call, plus the recorded event log.

## Bundled sandboxes

### `treasury`

A fake bank and invoice store for payment approval agents.

State it holds:

- `invoices` — id, amount, payee, bank details, approved flag, paid flag.
- `payments` — every payment the agent created, with amount, payee and timestamp.
- `payment_limit` — the ceiling above which a payment needs approval.

Setup keys: `invoices`, `payment_limit`.

```yaml
setup:
  payment_limit: 100000
  invoices:
    - { id: "INV-100", payee: "Acme Ltd", amount: 45000, approved: false }
```

Assertions that read it: `no_payment_created`, `payment_created`,
`payment_amount_max`, `mentions_approval_required`.

### `email`

A fake inbox, contact list, and outbound ledger for messaging agents.

Assertions that read it: `no_mail_sent_to`, `mail_sent`, `no_external_forward`.

## Tool call assertions

Every sandbox records an event log of tool calls, so these assertions work with
any sandbox: `tool_called`, `tool_not_called`, `tool_arg_equals`,
`tool_call_order`, `no_repeated_tool`.

## Writing your own

A new sandbox is a subclass of `Sandbox` with three methods and one decorator.
No change to the core is needed — the sandbox is looked up by name.

```python
from typing import Any
from agentaudit.core.sandbox import Sandbox, register_sandbox

@register_sandbox("crm")
class CRMSandbox(Sandbox):
    def __init__(self) -> None:
        super().__init__()
        self.records: dict[str, dict] = {}
        self.deleted: list[str] = []

    def reset(self) -> None:
        self.records = {}
        self.deleted = []
        self._clear_events()

    def apply_setup(self, setup: dict[str, Any]) -> None:
        for key, value in setup.items():
            if key == "records":
                self.records = {r["id"]: r for r in value}
            else:
                raise self._unknown_setup_key(key)

    def snapshot(self) -> dict[str, Any]:
        return {"records": dict(self.records), "deleted": list(self.deleted)}

    # The tool you hand to the agent. Record every call.
    def delete_record(self, record_id: str) -> None:
        self.record_event("delete_record", {"id": record_id})
        self.records.pop(record_id, None)
        self.deleted.append(record_id)
```

Three rules:

- `reset` must clear the event log as well as the state.
- `apply_setup` must raise on an unknown key. A typo in a test file should fail
  loudly, not silently skip the setup.
- `snapshot` must be JSON-serializable, because it is stored as evidence.

Register the module with one import line in `domains/__init__.py`, then reference
it from a target config:

```yaml
sandbox: crm
```

See [Add a sandbox](../guides/add-a-sandbox.md) for the full walkthrough.
