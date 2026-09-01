"""per-tenant LLM credentials for the attacker and judge roles

Until now the attacker/judge models came only from a deployment-owned file or
environment (`core/llm.py`), which a hosted tenant cannot reach. This table lets
an account supply its own endpoint, model and key.

`api_key` holds the literal, unlike `targets.secret_ref`. A target config is
partner-supplied input where a credential literal is a smell; this row is the
operator's own account setting, and there is no worker environment they can
provision instead. It is never returned by a read path -- see
`store.get_llm_settings`.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-01
"""

from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent against a database Store initialized directly (core/store.py:_SCHEMA).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_settings (
            org_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('attacker', 'judge')),
            endpoint TEXT NOT NULL,
            model TEXT NOT NULL,
            api_key TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (org_id, role),
            FOREIGN KEY (org_id) REFERENCES orgs(id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS llm_settings")
