"""orgs table + org_id on agents, runs, test_results

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-18
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

DEFAULT_ORG = "default"
_BACKFILL_TIME = "1970-01-01T00:00:00+00:00"


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def _org_expression(table: str) -> str:
    return "org_id" if "org_id" in _columns(table) else f"'{DEFAULT_ORG}'"


def _create_tenant_schema() -> None:
    op.execute(
        """
        CREATE TABLE agents (
            id TEXT NOT NULL,
            org_id TEXT NOT NULL,
            name TEXT NOT NULL,
            target_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (org_id, id),
            FOREIGN KEY (org_id) REFERENCES orgs(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            status TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            score_json TEXT NOT NULL,
            UNIQUE (org_id, id),
            FOREIGN KEY (org_id) REFERENCES orgs(id),
            FOREIGN KEY (org_id, agent_id) REFERENCES agents(org_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            test_id TEXT NOT NULL,
            category TEXT NOT NULL,
            risk TEXT NOT NULL,
            status TEXT NOT NULL,
            latency_ms REAL,
            result_json TEXT NOT NULL,
            FOREIGN KEY (org_id) REFERENCES orgs(id),
            FOREIGN KEY (org_id, run_id) REFERENCES runs(org_id, id)
        )
        """
    )


def _create_indexes() -> None:
    op.execute("CREATE INDEX idx_results_run ON test_results(run_id)")
    op.execute("CREATE INDEX idx_runs_agent ON runs(agent_id)")
    op.execute("CREATE INDEX idx_runs_org_started ON runs(org_id, started_at)")
    op.execute("CREATE INDEX idx_agents_org ON agents(org_id)")
    op.execute("CREATE INDEX idx_results_org ON test_results(org_id)")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS orgs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        f"INSERT OR IGNORE INTO orgs (id, name, created_at) "
        f"VALUES ('{DEFAULT_ORG}', '{DEFAULT_ORG}', '{_BACKFILL_TIME}')"
    )

    agent_org = _org_expression("agents")
    run_org = _org_expression("runs")
    result_org = _org_expression("test_results")

    # Preserve org rows from databases that Store already initialized with the T2 schema.
    for table, expression in (
        ("agents", agent_org),
        ("runs", run_org),
        ("test_results", result_org),
    ):
        op.execute(
            "INSERT OR IGNORE INTO orgs (id, name, created_at) "
            f"SELECT DISTINCT {expression}, {expression}, '{_BACKFILL_TIME}' FROM {table}"
        )

    # Rebuild every tenant-bearing table. ALTER COLUMN would leave temporary defaults and
    # the baseline's runs.agent_id foreign key pointing at a now non-unique agents.id.
    op.execute("ALTER TABLE test_results RENAME TO test_results_legacy")
    op.execute("ALTER TABLE runs RENAME TO runs_legacy")
    op.execute("ALTER TABLE agents RENAME TO agents_legacy")
    _create_tenant_schema()

    op.execute(
        "INSERT INTO agents (id, org_id, name, target_type, created_at) "
        f"SELECT id, {agent_org}, name, target_type, created_at FROM agents_legacy"
    )
    op.execute(
        "INSERT INTO runs (id, org_id, agent_id, started_at, finished_at, status, "
        "summary_json, score_json) "
        f"SELECT id, {run_org}, agent_id, started_at, finished_at, status, "
        "summary_json, score_json FROM runs_legacy"
    )
    op.execute(
        "INSERT INTO test_results (id, org_id, run_id, test_id, category, risk, status, "
        "latency_ms, result_json) "
        f"SELECT id, {result_org}, run_id, test_id, category, risk, status, latency_ms, "
        "result_json FROM test_results_legacy"
    )

    op.execute("DROP TABLE test_results_legacy")
    op.execute("DROP TABLE runs_legacy")
    op.execute("DROP TABLE agents_legacy")
    _create_indexes()

    violations = op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        sample = ", ".join(f"{row[0]} row {row[1]}" for row in violations[:3])
        raise RuntimeError(
            f"cannot migrate 0002: {len(violations)} foreign key violations remain ({sample})"
        )


def downgrade() -> None:
    collision = (
        op.get_bind()
        .exec_driver_sql("SELECT id FROM agents GROUP BY id HAVING COUNT(*) > 1 LIMIT 1")
        .fetchone()
    )
    if collision is not None:
        raise RuntimeError(
            f"cannot downgrade 0002: multiple organizations use agent id {collision[0]!r}"
        )

    op.execute("ALTER TABLE test_results RENAME TO test_results_tenant")
    op.execute("ALTER TABLE runs RENAME TO runs_tenant")
    op.execute("ALTER TABLE agents RENAME TO agents_tenant")

    op.execute(
        """
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            target_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL REFERENCES agents(id),
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            status TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            score_json TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(id),
            test_id TEXT NOT NULL,
            category TEXT NOT NULL,
            risk TEXT NOT NULL,
            status TEXT NOT NULL,
            latency_ms REAL,
            result_json TEXT NOT NULL
        )
        """
    )

    op.execute(
        "INSERT INTO agents (id, name, target_type, created_at) "
        "SELECT id, name, target_type, created_at FROM agents_tenant"
    )
    op.execute(
        "INSERT INTO runs (id, agent_id, started_at, finished_at, status, summary_json, "
        "score_json) SELECT id, agent_id, started_at, finished_at, status, summary_json, "
        "score_json FROM runs_tenant"
    )
    op.execute(
        "INSERT INTO test_results (id, run_id, test_id, category, risk, status, latency_ms, "
        "result_json) SELECT id, run_id, test_id, category, risk, status, latency_ms, "
        "result_json FROM test_results_tenant"
    )

    op.execute("DROP TABLE test_results_tenant")
    op.execute("DROP TABLE runs_tenant")
    op.execute("DROP TABLE agents_tenant")
    op.execute("DROP TABLE orgs")
    op.execute("CREATE INDEX idx_results_run ON test_results(run_id)")
    op.execute("CREATE INDEX idx_runs_agent ON runs(agent_id)")
