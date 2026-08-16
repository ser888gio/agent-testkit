"""targets, packs and pack_tests tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-18
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Keep in sync with backend/agentaudit/core/store.py:_SCHEMA.
TABLES = (
    """
    CREATE TABLE IF NOT EXISTS targets (
        id TEXT NOT NULL,
        org_id TEXT NOT NULL,
        name TEXT NOT NULL,
        config_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (org_id, id),
        FOREIGN KEY (org_id) REFERENCES orgs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS packs (
        id TEXT NOT NULL,
        org_id TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (org_id, id),
        FOREIGN KEY (org_id) REFERENCES orgs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pack_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        org_id TEXT NOT NULL,
        pack_id TEXT NOT NULL,
        test_json TEXT NOT NULL,
        FOREIGN KEY (org_id, pack_id) REFERENCES packs(org_id, id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_targets_org ON targets(org_id)",
    "CREATE INDEX IF NOT EXISTS idx_packs_org ON packs(org_id)",
    "CREATE INDEX IF NOT EXISTS idx_pack_tests_pack ON pack_tests(org_id, pack_id)",
)


def upgrade() -> None:
    for statement in TABLES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE pack_tests")
    op.execute("DROP TABLE packs")
    op.execute("DROP TABLE targets")
