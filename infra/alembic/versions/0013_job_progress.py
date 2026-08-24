"""track in-flight progress on the job, not the run

A run is written once, atomically, when it finishes: a half-written run is not
evidence, and every reader of `runs` would otherwise have to learn to exclude
one. So live progress lives on the `jobs` row instead, where it is already
understood to be transient operational state rather than an audit record.

Two columns: a counter and a small JSON blob of the most recent outcomes. The
blob is bounded by the writer, read whole, and discarded once the run lands.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates these columns (see core/store.py:_SCHEMA).
    existing = _columns("jobs")
    if "tests_total" not in existing:
        op.execute("ALTER TABLE jobs ADD COLUMN tests_total INTEGER")
    if "tests_done" not in existing:
        op.execute("ALTER TABLE jobs ADD COLUMN tests_done INTEGER NOT NULL DEFAULT 0")
    if "progress_json" not in existing:
        op.execute("ALTER TABLE jobs ADD COLUMN progress_json TEXT")


def downgrade() -> None:
    existing = _columns("jobs")
    for column in ("progress_json", "tests_done", "tests_total"):
        if column in existing:
            op.execute(f"ALTER TABLE jobs DROP COLUMN {column}")
