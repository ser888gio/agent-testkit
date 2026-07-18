# `agentkit.domains` — fake services and demo agents

Each subdirectory is one vertical: a `Sandbox` subclass modelling fake tools, plus demo
agent(s) used as targets in examples and tests.

- `treasury/` — `TreasurySandbox` (fake bank + invoice store), `create_agent`
- `email/` — `EmailSandbox` (fake inbox + contacts + outbound ledger), `create_agent`,
  `trusting_forwarder_agent` (a deliberately unsafe agent used to prove tests catch failures)

## Adding a vertical

This is additive by design and must not require any change to `core/`:

1. Subclass `agentkit.core.sandbox.Sandbox` and decorate with `@register_sandbox("name")`.
2. Implement `reset`, `apply_setup`, `snapshot`, and record side effects via `record_event`.
   Use `_unknown_setup_key` for unrecognised `setup` keys so bad packs fail loudly.
3. Add YAML packs under `agentkit/packs/<name>/` and a target config in `agentkit/config/`.
4. Register the import so the decorator runs — `cli.py` and `web/app.py` both import
   `agentkit.domains.<name>.sandbox` explicitly with `# noqa: F401`. Miss this and
   `build_sandbox` raises `unknown sandbox`.
5. Add `tests/test_<name>.py`.

## Constraints

- Domains import from `agentkit.core.sandbox` only. Never from `runner`, `store`, `reports`,
  or `web`.
- `snapshot()` must be JSON-serializable and deterministic — the generic `diff()` in
  `core/sandbox.py` compares snapshots directly, and non-determinism shows up as phantom
  diffs in the dashboard.
- Demo agents are fixtures, not products. Keep them small and readable; they exist to make
  the failure mode obvious, not to be good agents.

Validation: `python -m pytest tests/test_treasury.py tests/test_email.py tests/test_sandbox_core.py`
