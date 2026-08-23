"""let a job run a subset of its pack

Until now a job ran every test in its pack. Selecting a subset needs the chosen
ids to survive the queue, because the worker resolves the job from the database
alone -- the request that made the choice is long gone by the time it runs.

One nullable JSON column rather than a join table: the list is written once,
read whole, and never queried by element. NULL means "the whole pack", which is
what every existing row means and keeps the worker's default unchanged.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates this column (see core/store.py:_SCHEMA).
    if "test_ids_json" not in _columns("jobs"):
        op.execute("ALTER TABLE jobs ADD COLUMN test_ids_json TEXT")


def downgrade() -> None:
    if "test_ids_json" in _columns("jobs"):
        op.execute("ALTER TABLE jobs DROP COLUMN test_ids_json")
