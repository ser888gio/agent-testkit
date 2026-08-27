# `agentaudit.domains` — fake services and demo agents

Each subdirectory is one vertical: a `Sandbox` subclass modelling fake tools, plus demo
agent(s) used as targets in examples and tests.

- `treasury/` — `TreasurySandbox` (fake bank + invoice store), `create_agent`,
  `overtrusting_agent` (trusts the conversation transcript over seeded state; proves the
  authorization and trust-abuse packs actually catch something)
- `email/` — `EmailSandbox` (fake inbox + contacts + outbound ledger), `create_agent`,
  `trusting_forwarder_agent` (a deliberately unsafe agent used to prove tests catch failures)
- `declarative/` — `DeclarativeSandbox`: a generic `Sandbox` interpreting a YAML toolkit
  declaration (`agentaudit/toolkits/*.yaml`) instead of hand-written Python. Covers two
  resource archetypes -- `ledger` (a record table, generalizes `FakeBank`/invoices) and
  `mailbox` (an outbox, generalizes `FakeInbox`). One subclass per toolkit file is registered
  at import time; see [`docs/specs/declarative-sandboxes.md`](../../../../docs/specs/declarative-sandboxes.md).
- `support/` — worked example built on `declarative/`: a support-ticket refund agent
  (`create_agent`) and its unsafe foil (`overtrusting_agent`), both Python, against a sandbox
  declared entirely in `agentaudit/toolkits/support.yaml`.

## Two ways to add a vertical

Most new verticals should try the **declarative** path first (below) — it needs no `Sandbox`
subclass. Fall back to a **Python subclass** (the original "Adding a vertical" section below
this one) only when a vertical needs a resource shape `ledger`/`mailbox` cannot express.

### Declarative (no Sandbox subclass)

1. Write `agentaudit/toolkits/<name>.yaml`: a top-level `name` and one or more `resources`,
   each `{kind: ledger|mailbox, name: ..., ...}`. `build_sandbox("<name>")` works the moment
   this file exists and `agentaudit.domains` has been imported once.
2. Write a demo agent in Python (`backend/agentaudit/domains/<name>/agent.py`) against
   `agentaudit.domains.declarative.sandbox.DeclarativeSandbox` — call `sandbox.ledger(name)` /
   `sandbox.mailbox(name)` to reach a declared resource. This is the part that stays code, by
   design: PRD-009's "zero-code" claim is about the sandbox/domain layer, not the agent.
3. Add YAML packs under `agentaudit/packs/<name>/` and a target config in `agentaudit/config/`,
   same as any vertical. Generic assertions (`resource_not_created`, `no_message_to`,
   `state_unchanged` in `core/assertions.py`) work against any declared resource by name.
4. Full walkthrough with a worked example: `docs/specs/declarative-sandboxes.md`.

## Writing an unsafe fixture agent

Two traps, both learned the hard way in `treasury/overtrusting_agent.py`:

- **Keep conversation state on the sandbox, not in a closure.** Under isolation a single
  agent worker serves every test in a run, so closure state leaks turns between tests. The
  sandbox is reset per test, which is exactly the scope a transcript should have.
- **Never test a sandbox object for truthiness.** `_RemoteObject` forwards `__len__` over
  RPC, and a plain dataclass like `Invoice` has none, so `if invoice:` raises `TypeError`
  rather than checking existence. Write `if invoice is not None:`.

An unsafe fixture must also never raise: a pack that should report `failed` comes back
`error` if the agent crashes, which hides the very failure the pack exists to prove.

### Python subclass (escape hatch)

This is additive by design and must not require any change to `core/`:

1. Subclass `agentaudit.core.sandbox.Sandbox` and decorate with `@register_sandbox("name")`.
2. Implement `reset`, `apply_setup`, `snapshot`, and record side effects via `record_event`.
   Use `_unknown_setup_key` for unrecognised `setup` keys so bad packs fail loudly.
3. Add YAML packs under `agentaudit/packs/<name>/` and a target config in `agentaudit/config/`.
4. Add the import to `domains/__init__.py` so the decorator runs. That package is what
   `core.sandbox.load_builtin_sandboxes` imports by name; miss the line and `build_sandbox`
   raises `unknown sandbox`. No entry point needs touching.
5. Add `tests/test_<name>.py`.

## Constraints

- Domains import from `agentaudit.core.sandbox` only. Never from `runner`, `store`, `reports`,
  or `web`.
- `snapshot()` must be JSON-serializable and deterministic — the generic `diff()` in
  `core/sandbox.py` compares snapshots directly, and non-determinism shows up as phantom
  diffs in the dashboard.
- Demo agents are fixtures, not products. Keep them small and readable; they exist to make
  the failure mode obvious, not to be good agents.

Validation: `python -m pytest tests/test_treasury.py tests/test_email.py tests/test_sandbox_core.py`
