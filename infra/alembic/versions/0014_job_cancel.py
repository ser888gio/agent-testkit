"""let a caller ask a running job to stop

One column: a flag the worker checks between tests (`worker.py:execute_job`).
A queued job needs no flag -- cancelling it is a direct state flip to
'failed', which `state IN (...)` already allows, so no CHECK-constraint
rebuild is needed here.

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
    # creates this column (see core/store.py:_SCHEMA).
    if "cancel_requested" not in _columns("jobs"):
        op.execute("ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    if "cancel_requested" in _columns("jobs"):
        op.execute("ALTER TABLE jobs DROP COLUMN cancel_requested")
