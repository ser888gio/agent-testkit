"""which pipeline stage a running job is in

`tests_done/tests_total` only starts moving once the planner has produced a
list, so a job spends its first seconds -- resolving the target, confirming the
request shape against the live endpoint, loading the pack -- showing an
undifferentiated spinner. This column names the stage instead.

Operational state like `progress_json`: a stage name, never agent output.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-05
"""

from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates this column (see core/store.py:_SCHEMA).
    if "phase" not in _columns("jobs"):
        op.execute("ALTER TABLE jobs ADD COLUMN phase TEXT")


def downgrade() -> None:
    if "phase" in _columns("jobs"):
        op.execute("ALTER TABLE jobs DROP COLUMN phase")
