# PRD-006 — Skip sandbox-requiring tests when the target configures no sandbox

**Type:** Fix · **Status: IMPLEMENTED** (branch `fix/core-skip-without-sandbox`, commit `7d8cb81`)

## Problem
The quickstart's default path (`agentaudit run core --endpoint ...`, no target config)
reports three adaptive jailbreak tests as **failed** on every sandbox-less agent, with
assertion detail `"sandbox has no bank"`. Verified locally: a harmless echo stub scored 85%
pass with 3 high-risk "failures" — harness misconfiguration rendered as security findings.
A first-time user is taught in the first five minutes that results can be false, and every
subsequent real failure is discounted ("probably another false one"). Ties to Task 2 §1 and
the trust-calibration failure in pain-points.md.

## Proposed solution
In the runner, before executing a test, skip it with an explanatory reason when the target
declares no sandbox but the test requires one (`setup` keys or side-effect assertions —
`catalog.requires_sandbox`). A declared-but-wrong sandbox keeps failing closed:
misconfiguration must surface loudly. Reason text stored in `TestResult.error`.

## Success criteria
- Bare `run core` against any agent shows the 3 tests as SKIP with reason; zero false failures.
- Declared wrong-domain sandbox still yields failed/error (fail-closed preserved) — regression-tested.
- Full suite green including `tests/test_security_p0.py`; scoring excludes skipped tests (existing behavior).
- ✅ All met on the implementation branch (783 passed; end-to-end repro re-run).

## Priority & effort
P0 — first impressions gate adoption · Effort: S (done)

## Open questions
- Should the CLI hint "attach a treasury/email sandbox to unlock N action-safety tests"
  when skips > 0? (Follow-up UX, see PRD-008.)
