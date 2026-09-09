"""drop stored literal LLM API keys

`llm_settings.api_key` used to hold a tenant's key verbatim on an unencrypted
volume shared by every tenant. It now holds an environment reference (`${VAR}`)
that the worker resolves from its own environment, so every value written under
the old contract is a plaintext credential that must not survive the upgrade.

Deliberately destructive and irreversible: the rows are cleared rather than
rewritten, because a literal cannot be mechanically turned into a reference --
the operator has to provision the value on the worker first. Affected orgs
re-enter a reference in Settings; until they do, the adaptive roles fall back to
the deployment default or the scripted ladder, which is the same behaviour as
never having configured a key.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-08
"""

from __future__ import annotations

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE llm_settings SET api_key = NULL")


def downgrade() -> None:
    # Not reversible: the keys are gone, by design.
    pass
