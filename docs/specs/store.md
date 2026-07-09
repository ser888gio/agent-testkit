# feat/store — Spec

**Task 13 · Depends on: 1,2,12 · Files:** `agentkit/core/store.py`, `tests/test_store.py`

## Goal
Persist runs + scores to SQLite (stdlib `sqlite3`) and provide the read helpers the CLI and UI
need.

## Schema (authoritative)
```sql
CREATE TABLE agents (
    id TEXT PRIMARY KEY,             -- config id
    name TEXT NOT NULL,
    target_type TEXT NOT NULL,       -- 'callable' | 'http'
    created_at TEXT NOT NULL
);
CREATE TABLE runs (
    id TEXT PRIMARY KEY,             -- run_id (uuid4 hex)
    agent_id TEXT NOT NULL REFERENCES agents(id),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,            -- 'passed' | 'failed' (gate verdict rollup)
    summary_json TEXT NOT NULL,      -- counts by status/category
    score_json TEXT NOT NULL         -- ScoreReport.model_dump_json()
);
CREATE TABLE test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    test_id TEXT NOT NULL,
    category TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL,
    result_json TEXT NOT NULL        -- full TestResult incl. REDACTED request/response evidence
);
CREATE INDEX idx_results_run ON test_results(run_id);
CREATE INDEX idx_runs_agent ON runs(agent_id);
```
Evidence: request/response live **inside `result_json`**, already redacted by the runner
(task 11). `save_run` re-applies the `Redactor` as a defense-in-depth safety net and honors
`store_request/response` (drops to `null`).

## Public API
```python
class Store:
    def __init__(self, path: str = "agentkit.db"): ...   # creates/migrates on connect
    def save_run(self, agent: TargetConfig, run: RunResult, score: ScoreReport) -> None
    def list_agents(self) -> list[AgentRow]
    def list_runs(self, agent_id: str | None = None, limit: int = 50) -> list[RunRow]
    def get_run(self, run_id: str) -> tuple[RunResult, ScoreReport]
    def pass_fail_matrix(self, agent_id: str) -> Matrix   # latest run: category x test -> status
```

## Behavior
- `save_run` is one transaction: upsert agent, insert run, bulk-insert test_results. On error,
  rollback (no partial run).
- `runs.status` = `'passed'` if `score.gate_passed` else `'failed'`.
- Migration is idempotent `CREATE TABLE IF NOT EXISTS`; safe to call every connect.

## Failure behavior
- `get_run(unknown)` → `KeyError`/`None` (define one; tests assert it).
- Corrupt/older DB missing a table → migrate on open (never hard-fail on a fresh file).

## Examples
```python
s = Store(":memory:")
s.save_run(cfg, run, report)
run2, report2 = s.get_run(run.run_id)
run2 == run and report2 == report          # round-trip
s.pass_fail_matrix(cfg.id)                  # {category: {test_id: status}}
```

## Tests required
- `save_run` then `get_run` round-trips `RunResult` + `ScoreReport` identically.
- `list_runs`/`list_agents` return newest-first, respect `limit`.
- `pass_fail_matrix` reflects the latest run only.
- `store_response=False` at save → persisted `result_json.response is null`.
- Re-opening an existing DB does not error or duplicate schema.

## Done when
A run+score round-trips through SQLite unchanged, the matrix helper works, and stored evidence
honors the redaction/storage policy.
