"""correct stored runs that gated green on zero evidence

e34a76e made the gate fail closed when nothing passed and at least one test
errored, but only for runs made after it. Runs recorded before that still sit
in the store with status='passed' and a score of zero -- queryable evidence
that a run in which every test errored was a pass. For a tool whose output is
compliance evidence, leaving those is worse than the original bug: the fix is
invisible to anyone reading the history.

Re-derives, never reinterprets. A row is corrected only when the stored
`score_json` already says the run had no passing evidence (`passed == 0`) and
its results contain at least one error -- exactly `scoring.no_evidence`, the
condition that gates BLOCK today. Runs that cleanly failed everything were
already status='failed', and any run with a single pass is left alone.

`score_json.gate_passed` and `incomplete` are rewritten alongside `status`, so
the run row and the embedded report agree; a report rendered from a stored run
reads the same as one re-scored from scratch.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-08
"""

from __future__ import annotations

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

# SQLite ships json1 in every build Python bundles, and the store is
# SQLite-only (core/store.py), so the score_json rewrite stays in SQL rather
# than pulling rows through Python.
_STALE = """
    SELECT r.id FROM runs r
    WHERE r.status = 'passed'
      AND json_extract(r.score_json, '$.passed') = 0
      AND EXISTS (
        SELECT 1 FROM test_results t
        WHERE t.run_id = r.id AND t.status = 'error'
      )
"""


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE runs SET
            status = 'failed',
            score_json = json_set(
                json_set(score_json, '$.gate_passed', json('false')),
                '$.incomplete', json('true')
            )
        WHERE id IN ({_STALE})
        """
    )


def downgrade() -> None:
    # Not reversible: the corrected rows are indistinguishable from runs that
    # were always recorded as failed, and restoring a false green is not a
    # state this schema should be able to return to.
    pass
