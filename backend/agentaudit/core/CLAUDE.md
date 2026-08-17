# `agentaudit.core` — test engine

Imported as `agentaudit.core.*` (never `backend.agentaudit.core`). This is the trust-sensitive
half of the codebase: everything here either touches a live agent or produces the evidence
the rest of the system consumes.

## Entry points

- `runner.py:run` — the only execution path. Discovery → per-test sandbox reset → agent call
  (single- or multi-turn) → assertion evaluation → redaction → `RunResult`.
- `isolation.py:IsolatedRunner` — spawned run supervisor, nested killable agent worker,
  sandbox RPC boundary, process-tree cleanup, and CPU/memory ceilings.
- `loader.py:discover` — turns a packs directory into `TestCase` / `PythonTestCase` objects.
- `agent.py:build_agent` — `TargetConfig` → `CallableAgent` or `HTTPAgent`.
- `sandbox.py:build_sandbox` — name → registered `Sandbox` instance.
- `store.py:Store` — the only SQLite access point in the repository.
- `discovery.py:discover` — probes a live endpoint (through `runner.run`) into an `AgentProfile`.
- `attacker.py:build_refining_strategy` — optional attacker model that writes each adaptive
  turn from the agent's actual reply. Off unless `refine: true` **and**
  `AGENTAUDIT_ATTACKER_ENDPOINT`/`_MODEL` are set; falls back to the scripted ladder on any
  model failure, so runs stay offline and deterministic by default. See
  [`docs/specs/attacker.md`](../../../docs/specs/attacker.md).
- `planner.py:plan` / `apply_plan` — profile + catalogs → `HarnessPlan`, then the runnable half.
- `adapters.py:ADAPTERS` — promptfoo/garak report normalization into `TestResult`s.

## Local architecture constraints

- **`core` imports nothing from `domains`, `reports`, `web`, or `cli`.** It is the bottom of
  the dependency graph. If you need something from a layer above, the design is wrong.
- **`httpx` may be imported only in `agent.py`.** Any other module reaching the network is a
  boundary violation. This is why `HTTPAttacker` (the attacker-model client for
  `attacker.py`) lives in `agent.py` rather than beside the logic that uses it. Enforced by
  `tests/test_security_p0.py::test_httpx_is_imported_in_exactly_one_core_module`.
- **Runner/control-plane split inside this package:** `agent.py`, `sandbox.py`,
  `redaction.py`, `runner.py` are runner-side. `scoring.py`, `store.py`, `compliance.py`,
  `regressions.py` are control-plane-side and must operate purely on already-redacted
  `RunResult`/`ScoreReport` values.
- **Redaction ordering is a security property.** `runner.py` redacts before building a
  `TestResult`; `store.py:save_run` re-applies the `Redactor` before writing. Do not remove
  either pass on the grounds that the other exists — the redundancy is deliberate.
- **`runner.py` must not raise.** Wrap every agent/sandbox interaction so failures become
  `Status.ERROR` results. A traceback escaping `run()` is a bug.
- **`EvidencePolicy` is independent of redaction.** `store_request`/`store_response` can drop
  evidence entirely (`None`) even after redaction. Honour both.

## Contracts — changing these breaks every consumer

`schema.py` (`TestCase`, `TestResult`, `RunResult`, `Category`, `Risk`, `Status`),
`config.py` (`TargetConfig` and `${ENV_VAR}` interpolation), and the assertion `REGISTRY` in
`assertions.py`. A change here needs the full test suite plus a check of
`reports/`, `web/app.py`, and `cli.py`. Adding a `Category` or `Risk` value also affects
`scoring.py` weights and `compliance.py` control mapping.

## Adding an assertion

Write the function, register it in `assertions.py:REGISTRY`, add a case to
`tests/test_assertions.py`, and confirm `loader.py` validation accepts it (the loader
rejects unknown assertion names at discovery time). YAML packs reference it by name.

## Testing expectations

One `tests/test_<module>.py` per module here; keep that mapping. Every new branch in
`runner.py` needs a test that exercises the failure path, not just the happy path.

Validation: `python -m pytest tests/test_runner.py tests/test_assertions.py tests/test_schema.py`
then the full suite (it is ~4s).

Per-module specs live in [`docs/specs/`](../../../docs/specs/) — one file per module here.
