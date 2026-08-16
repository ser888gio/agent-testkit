"""store the harness plan a run executed

A run that cannot say why it chose its tests is not evidence, it is a number.
The plan lands in one nullable JSON column on `runs` rather than its own table:
it is read whole, written once, and never queried by field.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-16
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates this column (see core/store.py:_SCHEMA).
    if "plan_json" not in _columns("runs"):
        op.execute("ALTER TABLE runs ADD COLUMN plan_json TEXT")


def downgrade() -> None:
    if "plan_json" in _columns("runs"):
        op.execute("ALTER TABLE runs DROP COLUMN plan_json")
