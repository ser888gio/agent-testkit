"""record the last successful job heartbeat

The lease expiry answers whether a job may be reclaimed.  ``heartbeat_at`` is
the audit/debug timestamp for the last renewal and is intentionally separate
from the expiry value.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    if "heartbeat_at" not in _columns("jobs"):
        op.execute("ALTER TABLE jobs ADD COLUMN heartbeat_at TEXT")


def downgrade() -> None:
    if "heartbeat_at" in _columns("jobs"):
        op.execute("ALTER TABLE jobs DROP COLUMN heartbeat_at")
