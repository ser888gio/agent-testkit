"""the attack transforms a job expands its planned tests with

Transforms were reachable only from the CLI (`agentaudit run --attack`), so a
dashboard-launched job always ran the pack as written and the expansion step in
`core/audit.py` was a no-op. This column carries the caller's choice onto the
job row, which is what lets the worker report the stage.

Names are validated at enqueue against `core.attacks.TRANSFORMS`, so this holds
a JSON list of known names or NULL for "run the pack as written".

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-05
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates this column (see core/store.py:_SCHEMA).
    if "attack_transforms_json" not in _columns("jobs"):
        op.execute("ALTER TABLE jobs ADD COLUMN attack_transforms_json TEXT")


def downgrade() -> None:
    if "attack_transforms_json" in _columns("jobs"):
        op.execute("ALTER TABLE jobs DROP COLUMN attack_transforms_json")
