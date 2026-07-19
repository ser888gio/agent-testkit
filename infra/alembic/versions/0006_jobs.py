"""jobs queue with lease fields

A jobs table plus polling workers is the queue; there is no broker. Leases are
explicit (`lease_owner` + `lease_expires_at`) rather than inferred from a stale
`started_at`, so a slow-but-alive worker that keeps heartbeating is never
reclaimed out from under itself.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates this table (see core/store.py:_SCHEMA).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
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
            FOREIGN KEY (org_id) REFERENCES orgs(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(state, priority DESC, created_at)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_org ON jobs(org_id, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_jobs_org")
    op.execute("DROP INDEX IF EXISTS idx_jobs_queue")
    op.execute("DROP TABLE IF EXISTS jobs")
