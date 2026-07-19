"""per-target egress allowlist

`HTTPSpec.endpoint` is partner-supplied and handed to httpx, so an unrestricted
worker is an SSRF primitive. The allowlist lives on the target because that is
the grain at which a partner declares which host they actually operate.

Stored as a JSON array of exact, normalized hosts. No wildcards.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade() -> None:
    # Idempotent against a database Store initialized directly.
    if "allowed_hosts" not in _columns("targets"):
        op.execute("ALTER TABLE targets ADD COLUMN allowed_hosts TEXT")


def downgrade() -> None:
    if "allowed_hosts" in _columns("targets"):
        op.execute("ALTER TABLE targets DROP COLUMN allowed_hosts")
