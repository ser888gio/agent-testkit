# `agentaudit.core.store` — Specification

## Goal

Persist tenant-owned runs, scores, targets, and test packs to SQLite and provide the helpers
used by the CLI and dashboard. `Store` is the repository's only application SQL boundary.

## Schema (authoritative)

```sql
CREATE TABLE orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE agents (
    id TEXT NOT NULL,                -- config id, unique within an org
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    target_type TEXT NOT NULL,       -- 'callable' | 'http'
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, id),
    FOREIGN KEY (org_id) REFERENCES orgs(id)
);
CREATE TABLE runs (
    id TEXT PRIMARY KEY,             -- run_id (uuid4 hex)
    org_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,            -- 'passed' | 'failed' (gate verdict rollup)
    summary_json TEXT NOT NULL,      -- counts by status/category
    score_json TEXT NOT NULL,        -- ScoreReport.model_dump_json()
    UNIQUE (org_id, id),
    FOREIGN KEY (org_id) REFERENCES orgs(id),
    FOREIGN KEY (org_id, agent_id) REFERENCES agents(org_id, id)
);
CREATE TABLE test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    category TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL,
    result_json TEXT NOT NULL,       -- full, already-redacted TestResult
    FOREIGN KEY (org_id) REFERENCES orgs(id),
    FOREIGN KEY (org_id, run_id) REFERENCES runs(org_id, id)
);
CREATE TABLE targets (
    id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,       -- raw config with ${ENV_VAR} references intact
    created_at TEXT NOT NULL,
    secret_ref TEXT,                 -- opaque scheme:// reference; never a resolved secret
    PRIMARY KEY (org_id, id),
    FOREIGN KEY (org_id) REFERENCES orgs(id)
);
CREATE TABLE packs (
    id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, id),
    FOREIGN KEY (org_id) REFERENCES orgs(id)
);
CREATE TABLE pack_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    test_json TEXT NOT NULL,
    UNIQUE (org_id, pack_id, test_id),
    FOREIGN KEY (org_id, pack_id) REFERENCES packs(org_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_targets_org ON targets(org_id);
CREATE INDEX idx_packs_org ON packs(org_id);
CREATE INDEX idx_pack_tests_pack ON pack_tests(org_id, pack_id);
CREATE INDEX idx_results_run ON test_results(run_id);
CREATE INDEX idx_runs_agent ON runs(agent_id);
CREATE INDEX idx_runs_org_started ON runs(org_id, started_at);
CREATE INDEX idx_agents_org ON agents(org_id);
CREATE INDEX idx_results_org ON test_results(org_id);
```

Request/response evidence lives inside `result_json`. The runner redacts it before creating a
`TestResult`; `save_run` reapplies redaction as defense in depth and honors the evidence policy.

## Public API

```python
class Store:
    def __init__(self, path: str = "database/agentaudit.db"): ...
    def save_run(
        self, org_id: str, agent: TargetConfig, run: RunResult, score: ScoreReport
    ) -> None
    def list_agents(self, org_id: str) -> list[AgentRow]
    def list_tests(self, org_id: str) -> list[dict]
    def list_runs(
        self, org_id: str, agent_id: str | None = None, limit: int = 50
    ) -> list[RunRow]
    def run_count(self, org_id: str, agent_id: str) -> int
    def get_run(self, org_id: str, run_id: str) -> tuple[RunResult, ScoreReport]
    def pass_fail_matrix(self, org_id: str, agent_id: str) -> Matrix
    def save_target(
        self, org_id: str, target_id: str, name: str, config: dict,
        *, secret_ref: str | None = None
    ) -> None
    def get_target(self, org_id: str, target_id: str) -> dict
    def get_target_secret_ref(self, org_id: str, target_id: str) -> str | None
    def list_targets(self, org_id: str) -> list[TargetRow]
    def delete_target(self, org_id: str, target_id: str) -> bool
    def save_pack(self, org_id: str, pack_id: str, name: str, tests: list[dict]) -> None
    def save_pack_test(self, org_id: str, pack_id: str, test: dict) -> None
    def get_pack_tests(self, org_id: str, pack_id: str) -> list[dict]
    def list_packs(self, org_id: str) -> list[PackRow]
    def delete_pack_test(self, org_id: str, pack_id: str, test_id: str) -> bool
    def delete_pack(self, org_id: str, pack_id: str) -> bool
```

`org_id` is always the required leading public argument and has no default. The CLI and the
pre-authentication dashboard pass `DEFAULT_ORG` explicitly until identity work supplies the
validated tenant claim.

## Behavior

- `save_run` is one transaction: ensure the org exists, upsert its agent, insert its run, and
  bulk-insert tenant-matched test results. Any error rolls the transaction back.
- `save_run` sanitizes a copy of every evidence field immediately before serialization. It
  independently reapplies `Redactor` and `EvidencePolicy`, even when the runner already did so.
- `save_target` validates the raw target without persisting interpolated values. Sensitive
  configuration values must be `${ENV_VAR}` references backed by a separate `scheme://`
  `secret_ref`; target row and config IDs must match.
- Pack writes validate complete `TestCase` values before opening the transaction. Test IDs are
  unique within `(org_id, pack_id)`. Pack and pack-test deletion is atomic and org-scoped.
- Every read filters by the caller's `org_id`; tenant-bearing joins match both tenant and row ID.
- SQLite foreign-key enforcement is enabled on every Store connection.
- `runs.status` is `passed` when `score.gate_passed`, otherwise `failed`.
- Store construction creates the current schema for a new database. It does not upgrade an
  older schema: run `agentaudit migrate --db <path>` before opening a pre-T2 database.

## Failure behavior

- `get_run(org_id, unknown_or_foreign_run)` raises `KeyError` in both cases, so another
  tenant's run existence is not disclosed.
- Omitting the required `org_id` raises `TypeError` at the Python boundary.
- A tenant marker inconsistent with its parent row fails a database constraint.
- Target/pack deletion returns `False` for both missing and foreign rows, avoiding an existence
  oracle. Target and pack getters raise `KeyError` for both cases.
- Literal credentials, invalid target identity, malformed tests, and duplicate pack test IDs are
  rejected before any row is written.

## Example

```python
s = Store(":memory:")
s.save_run("org-a", cfg, run, report)
run2, report2 = s.get_run("org-a", run.run_id)
run2 == run and report2 == report
s.pass_fail_matrix("org-a", cfg.id)  # {category: {test_id: status}}
```

## Tests required

- `save_run` then `get_run` round-trips `RunResult` and `ScoreReport`.
- `list_runs`/`list_agents` return newest-first and respect `limit`.
- `pass_fail_matrix` reflects the latest run only.
- A two-org fixture gives tenants different agents, tests, and statuses and proves every read
  returns only the caller's rows.
- `get_run` treats a foreign run exactly like an unknown run.
- Every public method has required leading `org_id`.
- Migrating a populated baseline preserves every row under `DEFAULT_ORG`, produces the same
  constraints/defaults/indexes as direct Store creation, and passes `PRAGMA foreign_key_check`.
- Migrated and directly-created schemas match for targets, packs, and pack tests as well as runs.
- Store-boundary tests inject raw evidence and prove secrets are absent from SQLite JSON.
- Target tests inspect raw `config_json` and prove only placeholders and the separate
  `secret_ref` are retained.
- Pack tests cover duplicate rejection, scoped item CRUD, and parent/child deletion.
- `store_response=False` persists a null response.
- Reopening a database does not duplicate schema.

## Done when

Runs and scores round-trip without crossing tenant boundaries, migrated and directly-created
databases enforce the same schema, and stored evidence honors redaction and storage policy.
