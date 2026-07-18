"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-07-18
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Mirrors the schema Store already creates today (agents, runs, test_results).
# IF NOT EXISTS makes this safe to run against a DB Store has already initialized directly.


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            target_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
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
        CREATE TABLE IF NOT EXISTS test_results (
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
    op.execute("CREATE INDEX IF NOT EXISTS idx_results_run ON test_results(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_runs_agent")
    op.execute("DROP INDEX IF EXISTS idx_results_run")
    op.execute("DROP TABLE IF EXISTS test_results")
    op.execute("DROP TABLE IF EXISTS runs")
    op.execute("DROP TABLE IF EXISTS agents")
