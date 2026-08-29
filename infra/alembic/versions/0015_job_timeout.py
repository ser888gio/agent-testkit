"""give a job an optional wall-clock budget and an 'expired' terminal state

A job that outruns its `timeout_seconds` is not a cancel and not a generic
failure: it stopped because it was told how long it had. That is its own
terminal state so a reader can tell "the agent ran out of time" from "the agent
broke" without parsing error text.

Widening the `state` CHECK to admit 'expired' means rebuilding the table, the
same way 0014 did to admit 'cancelled': SQLite cannot ALTER a CHECK in place.
The new `timeout_seconds` column rides along in the same rebuild rather than a
second ADD COLUMN pass. This mirrors the full column set `core/store.py`'s
`_SCHEMA` already creates for a fresh database, so a fresh DB and a migrated
one end up with the identical `jobs` table.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# `timeout_seconds` is absent on purpose: upgrade lets its DEFAULT NULL fill
# the copied rows, and downgrade drops it with the old table.
_CARRIED = (
    "id, org_id, target_id, pack_id, state, run_id, created_by, error, priority, "
    "attempt_count, created_at, started_at, finished_at, lease_owner, lease_expires_at, "
    "heartbeat_at, test_ids_json, tests_total, tests_done, progress_json, cancel_requested"
)


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def _rebuild(states: str, extra: str) -> None:
    op.execute("DROP INDEX IF EXISTS idx_jobs_queue")
    op.execute("DROP INDEX IF EXISTS idx_jobs_org")
    op.execute(
        f"""
        CREATE TABLE jobs_new (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            pack_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ({states})),
            run_id TEXT,
            created_by TEXT,
            error TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            lease_owner TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            test_ids_json TEXT,
            tests_total INTEGER,
            tests_done INTEGER NOT NULL DEFAULT 0,
            progress_json TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            {extra}
            FOREIGN KEY (org_id) REFERENCES orgs(id)
        )
        """
    )
    op.execute(f"INSERT INTO jobs_new ({_CARRIED}) SELECT {_CARRIED} FROM jobs")
    op.execute("DROP TABLE jobs")
    op.execute("ALTER TABLE jobs_new RENAME TO jobs")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(state, priority DESC, created_at)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_org ON jobs(org_id, created_at)")


def upgrade() -> None:
    # Idempotent against a database Store initialized directly (core/store.py:_SCHEMA).
    if "timeout_seconds" in _columns("jobs"):
        return
    _rebuild(
        "'queued', 'running', 'done', 'failed', 'cancelled', 'expired'",
        "timeout_seconds INTEGER,",
    )


def downgrade() -> None:
    if "timeout_seconds" not in _columns("jobs"):
        return
    # 'expired' has no pre-0015 equivalent, so it becomes a failure carrying
    # the reason in error text.
    op.execute("UPDATE jobs SET state = 'failed', error = 'timed out' WHERE state = 'expired'")
    _rebuild("'queued', 'running', 'done', 'failed', 'cancelled'", "")
