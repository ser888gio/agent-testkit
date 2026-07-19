"""artifact metadata, org-scoped

Blob storage is deferred, but the layout is not. Evidence blobs are where
cross-tenant leakage reappears, because the first component to write a file
inherits none of the row-level scoping. Fixing `{org_id}/{run_id}/{artifact_id}`
now makes object storage a backend swap rather than a migration.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates this table (see core/store.py:_SCHEMA).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT NOT NULL,
            org_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            size INTEGER NOT NULL,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (org_id, id),
            UNIQUE (path),
            FOREIGN KEY (org_id) REFERENCES orgs(id),
            FOREIGN KEY (org_id, run_id) REFERENCES runs(org_id, id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(org_id, run_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_artifacts_run")
    op.execute("DROP TABLE IF EXISTS artifacts")
