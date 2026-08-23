# `agentaudit.core` — test engine

Imported as `agentaudit.core.*` (never `backend.agentaudit.core`). This is the trust-sensitive
half of the codebase: everything here either touches a live agent or produces the evidence
the rest of the system consumes.

## Entry points

- `audit.py:execute` — the assembled run: discover → plan → attack expansion → run →
  score. Every entry point that grades an agent (`cli.run_cmd`, `worker.execute_job`)
  goes through it; neither may spell the sequence out again.
- `findings.py` — what failed, in what order, and why. Every renderer, the dashboard and
  the store derive failures through it; none of them re-derive.
- `runner.py:run` — the only execution path. Discovery → per-test sandbox reset → agent call
  (single- or multi-turn) → assertion evaluation → redaction → `RunResult`.
- `isolation.py:IsolatedRunner` — spawned run supervisor, nested killable agent worker,
  sandbox RPC boundary, process-tree cleanup, and CPU/memory ceilings. It owns the child's
  deadline too (`run_test(test)` derives it); the runner keeps only lifecycle.
- `loader.py:discover` — turns a packs directory into `TestCase` / `PythonTestCase` objects.
- `agent.py:build_agent` — `TargetConfig` → `CallableAgent` or `HTTPAgent`.
- `sandbox.py:build_sandbox` — name → registered `Sandbox` instance. Loads the built-in
  verticals itself (`load_builtin_sandboxes`, by module name), so no caller carries a
  registration import; `sandbox_modules()` reports what a spawned child must import.
- `store.py:Store` — the only SQLite access point in the repository.
- `credentials.py` — what a credential looks like, and where one may appear. One
  vocabulary with two uses: `Redactor` masks it out of evidence, `Store.save_target`
  refuses to persist it in a config. Imports nothing from `agentaudit`.
- `discovery.py:discover` — probes a live endpoint (through `runner.run`) into an `AgentProfile`.
- `attacker.py:build_refining_strategy` — optional attacker model that writes each adaptive
  turn from the agent's actual reply. Off unless `refine: true` **and**
  `AGENTAUDIT_ATTACKER_ENDPOINT`/`_MODEL` are set; falls back to the scripted ladder on any
  model failure, so runs stay offline and deterministic by default. See
  [`docs/specs/attacker.md`](../../../docs/specs/attacker.md).
- `judge.py:build_judge` — optional model that decides whether an adaptive attack landed,
  replacing the `stop_on` substring check. Off unless `AGENTAUDIT_JUDGE_ENDPOINT`/`_MODEL`
  are set; falls back to substrings on any failure. It is a **stop condition, not a
  scorer** — assertions still decide pass/fail, and a model verdict must never reach
  `Status`. See [`docs/specs/judge.md`](../../../docs/specs/judge.md).
- `jsonx.py:extract_json` — pulls the first JSON object out of a model reply that may be
  fenced, prefaced, or trailed by prose. Used by every module that asks a model for JSON.
- `planner.py:plan` / `apply_plan` — profile + catalogs → `HarnessPlan`, then the runnable half.
- `archive.py:Archive` — one elite attack per `(Category, style)` cell, so generated attacks
  seek coverage instead of converging on one framing. `empty_cells()` is the structural
  answer to "what did you not test". Pure, offline, deterministic.
- `evolve.py:evolve` — generate → validate → prune → run → admit. Off unless
  `AGENTAUDIT_ATTACKER_ENDPOINT`/`_MODEL` are set, so `run` stays offline. Holds no `Store`;
  the CLI persists what it returns. See [`docs/specs/evolve.md`](../../../docs/specs/evolve.md).
- `adapters.py:ADAPTERS` — promptfoo/garak: what to run (`catalog`), running it
  (`execute`, spawning the tool), and its report normalized into `TestResult`s
  (`normalize`). `execute` is runner-side — it reaches a live agent, via a spawned
  process that does its own DNS, so the egress pin does not bind it.

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
- **Credential shapes live in `credentials.py`, not in the modules that use them.**
  Adding a key format there fixes both the redactor and the config check; adding it to
  only one is how `Basic ...` ended up refused at the config door and unmasked in
  evidence. `tests/test_credentials.py` walks the vocabulary and asserts both halves.
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
