"""whether a job attacks adaptively after running its pack

The generate -> attack -> refine loop (`core/campaign.py`) was reachable only
from the CLI (`agentaudit evolve --campaign`), so a dashboard run was always
fixed-pack tests times static attack transforms and no run report ever showed a
generated test. This column carries the caller's choice onto the job row.

A boolean, not a budget: the budget is a server-side constant
(`worker.ADAPTIVE_BUDGET`) so a browser cannot raise the number of metered model
calls a run makes.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-05
"""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates this column (see core/store.py:_SCHEMA).
    if "adaptive" not in _columns("jobs"):
        op.execute("ALTER TABLE jobs ADD COLUMN adaptive INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    if "adaptive" in _columns("jobs"):
        op.execute("ALTER TABLE jobs DROP COLUMN adaptive")
