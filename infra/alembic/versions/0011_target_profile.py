"""store the discovered profile alongside its target

A profile describes an agent, not a run: re-discovering the same target replaces
what we knew rather than appending to a history. So it lands in one nullable
JSON column on `targets`, read whole and written whole, the same shape as
`runs.plan_json` in 0010.

`profiled_at` is separate rather than read out of the JSON because "when did we
last look at this agent" is the question the UI asks to decide whether the
profile is stale, and digging it out of a blob to sort on it is the wrong shape.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates these columns (see core/store.py:_SCHEMA).
    existing = _columns("targets")
    if "profile_json" not in existing:
        op.execute("ALTER TABLE targets ADD COLUMN profile_json TEXT")
    if "profiled_at" not in existing:
        op.execute("ALTER TABLE targets ADD COLUMN profiled_at TEXT")


def downgrade() -> None:
    existing = _columns("targets")
    if "profiled_at" in existing:
        op.execute("ALTER TABLE targets DROP COLUMN profiled_at")
    if "profile_json" in existing:
        op.execute("ALTER TABLE targets DROP COLUMN profile_json")
