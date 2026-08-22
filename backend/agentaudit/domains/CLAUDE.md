# `agentaudit.domains` — fake services and demo agents

Each subdirectory is one vertical: a `Sandbox` subclass modelling fake tools, plus demo
agent(s) used as targets in examples and tests.

- `treasury/` — `TreasurySandbox` (fake bank + invoice store), `create_agent`,
  `overtrusting_agent` (trusts the conversation transcript over seeded state; proves the
  authorization and trust-abuse packs actually catch something)
- `email/` — `EmailSandbox` (fake inbox + contacts + outbound ledger), `create_agent`,
  `trusting_forwarder_agent` (a deliberately unsafe agent used to prove tests catch failures)

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

## Adding a vertical

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
