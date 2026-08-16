---
description: Review the current diff for correctness, regressions, and boundary violations.
argument-hint: [optional base ref, defaults to unstaged + staged changes]
---

Review: **$ARGUMENTS**

Review the diff independently — do not assume the implementation was correct because you or
another session wrote it. Read the diff first (`git diff`, `git diff --staged`, or
`git diff <base>...HEAD`; the default branch is `develop`).

For a substantial diff, delegate to the `code-reviewer` subagent and verify its findings
yourself before reporting.

## Check, in priority order

1. **Correctness and regressions.** Does it do what it claims? Check every consumer of a
   changed signature, schema field, or contract — including YAML packs in `agentaudit/packs/`
   and Jinja templates in `frontend/agentaudit/web/templates/`, which reference names as
   strings and are invisible to Python tooling.
2. **Repository invariants.** Runner never raises. Redaction runs in `runner.py` *and*
   `store.py` (both passes deliberate). No raw request/response logging. Compliance fails
   closed. `EvidencePolicy` honoured independently of redaction.
3. **Architectural boundaries.** `core` imports nothing from `domains`/`reports`/`web`/`cli`.
   `httpx` only in `core/agent.py`. SQL only in `core/store.py`. No `# noqa: F401` sandbox
   registration import deleted as "dead code".
4. **Missing tests.** New behaviour needs a case in `tests/test_<module>.py`. Failure paths
   matter more than happy paths here. Side-effect assertions beat text assertions.
5. **Unnecessary scope.** Unrelated refactoring or reformatting.

Also flag: renamed pack `id:` values (breaks `agentaudit compare` history), new `Category` or
`Risk` enum values without matching `scoring.py`/`compliance.py` updates, edits to generated
paths, and anything widening the web app's bind address or path handling.

## Verify, don't reason

Run `python -m pytest` and `python -m ruff check .` and report the real
output.

## Report

Group as **Blocking** / **Should fix** / **Optional**. Each finding: `path:line`, the defect
in one sentence, and a concrete failure scenario. If the diff is clean, say so — do not
manufacture findings.
