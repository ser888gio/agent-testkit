"""whether a test result came from a pack, the evolve loop, or a promotion

`core/lifecycle.py:origin_of` already derives authored/generated/promoted from
the test_id prefix, and nothing needed a stored column for it -- reports
(coverage.py) compute it on read. But ad hoc analysis of the run history
(tools/analyze_runs.py) means every consumer either re-derives the prefix
rule or imports agentaudit just to run a query. Persisting it lets origin be
filtered/grouped in plain SQL without the import.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-08
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates this column (see core/store.py:_SCHEMA).
    if "origin" not in _columns("test_results"):
        op.execute("ALTER TABLE test_results ADD COLUMN origin TEXT NOT NULL DEFAULT 'authored'")
        # Backfill existing rows from their test_id prefix instead of leaving
        # every historical result stamped 'authored' regardless of how it was
        # produced.
        op.execute(
            "UPDATE test_results SET origin = 'generated' "
            "WHERE test_id = 'generated' OR test_id LIKE 'generated.%'"
        )
        op.execute(
            "UPDATE test_results SET origin = 'promoted' "
            "WHERE test_id = 'promoted' OR test_id LIKE 'promoted.%'"
        )


def downgrade() -> None:
    if "origin" in _columns("test_results"):
        op.execute("ALTER TABLE test_results DROP COLUMN origin")
