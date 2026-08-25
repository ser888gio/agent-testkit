"""let a queued or running job be cancelled

Cancellation is cooperative: `cancel_requested` is a flag the worker checks
between tests, not a preemption mechanism. A queued job with no worker yet
transitions to 'cancelled' immediately on request instead.

SQLite cannot ALTER a CHECK constraint in place, so widening `state` to admit
'cancelled' means rebuilding the table: create the new shape, copy every row,
drop the old table, rename. This mirrors the full column set `core/store.py`'s
`_SCHEMA` already creates for a fresh database, so a fresh DB and a migrated
one end up with the identical `jobs` table. Column lists are written out in
full, not built from an interpolated constant, so the statements stay plain
string literals.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates the widened constraint and the column (see core/store.py:_SCHEMA).
    if "cancel_requested" in _columns("jobs"):
        return
    op.execute("DROP INDEX IF EXISTS idx_jobs_queue")
    op.execute("DROP INDEX IF EXISTS idx_jobs_org")
    op.execute(
        """
        CREATE TABLE jobs_new (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            pack_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('queued', 'running', 'done', 'failed', 'cancelled')
            ),
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
            FOREIGN KEY (org_id) REFERENCES orgs(id)
        )
        """
    )
    # cancel_requested is left out of both column lists on purpose: the old
    # `jobs` has no such column to read, so omitting it from the INSERT target
    # list lets its own DEFAULT 0 fill every copied row.
    op.execute(
        "INSERT INTO jobs_new (id, org_id, target_id, pack_id, state, run_id, created_by, "
        "error, priority, attempt_count, created_at, started_at, finished_at, lease_owner, "
        "lease_expires_at, heartbeat_at, test_ids_json, tests_total, tests_done, progress_json) "
        "SELECT id, org_id, target_id, pack_id, state, run_id, created_by, error, priority, "
        "attempt_count, created_at, started_at, finished_at, lease_owner, lease_expires_at, "
        "heartbeat_at, test_ids_json, tests_total, tests_done, progress_json FROM jobs"
    )
    op.execute("DROP TABLE jobs")
    op.execute("ALTER TABLE jobs_new RENAME TO jobs")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(state, priority DESC, created_at)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_org ON jobs(org_id, created_at)")


def downgrade() -> None:
    if "cancel_requested" not in _columns("jobs"):
        return
    op.execute("UPDATE jobs SET state = 'failed', error = 'cancelled' WHERE state = 'cancelled'")
    op.execute("DROP INDEX IF EXISTS idx_jobs_queue")
    op.execute("DROP INDEX IF EXISTS idx_jobs_org")
    op.execute(
        """
        CREATE TABLE jobs_new (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            pack_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed')),
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
            FOREIGN KEY (org_id) REFERENCES orgs(id)
        )
        """
    )
    op.execute(
        "INSERT INTO jobs_new (id, org_id, target_id, pack_id, state, run_id, created_by, "
        "error, priority, attempt_count, created_at, started_at, finished_at, lease_owner, "
        "lease_expires_at, heartbeat_at, test_ids_json, tests_total, tests_done, progress_json) "
        "SELECT id, org_id, target_id, pack_id, state, run_id, created_by, error, priority, "
        "attempt_count, created_at, started_at, finished_at, lease_owner, lease_expires_at, "
        "heartbeat_at, test_ids_json, tests_total, tests_done, progress_json FROM jobs"
    )
    op.execute("DROP TABLE jobs")
    op.execute("ALTER TABLE jobs_new RENAME TO jobs")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(state, priority DESC, created_at)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_org ON jobs(org_id, created_at)")
