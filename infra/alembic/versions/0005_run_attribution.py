"""run and authored-test attribution

Records who launched a run / authored a test: the Keycloak `sub` plus the email
denormalized for display. Nullable, because runs launched by the CLI have no
human principal and rows predating this revision have no attribution to recover.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_COLUMNS = ("created_by", "created_by_email")
_TABLES = ("runs", "pack_tests")


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly, which already
    # creates these columns (see core/store.py:_SCHEMA).
    for table in _TABLES:
        existing = _columns(table)
        for column in _COLUMNS:
            if column not in existing:
                op.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")


def downgrade() -> None:
    for table in _TABLES:
        existing = _columns(table)
        for column in _COLUMNS:
            if column in existing:
                op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
