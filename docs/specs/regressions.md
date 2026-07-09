# feat/regressions — Spec

**Task 19 · Depends on: 12,13 · Files:** `agentkit/core/regressions.py`,
`tests/test_regressions.py` (+ CLI/UI wiring)

## Goal
Compare two runs (e.g. agent v1.2.0 vs v1.3.0) so the tool becomes a release-safety system,
not just a test runner.

## Public API
```python
class TestDelta(BaseModel):
    test_id: str
    before: Status | None            # None if the test is new/removed
    after: Status | None
    latency_before_ms: float | None
    latency_after_ms: float | None

class RunDiff(BaseModel):
    newly_failing: list[str]         # passed/absent -> failed/error
    newly_passing: list[str]         # failed/error -> passed
    still_failing: list[str]
    added: list[str]
    removed: list[str]
    latency_deltas: list[TestDelta]  # only tests present in both
    score_delta: dict[str, float]    # overall, pass_rate, per-category (after - before)
    critical_regressions: list[str]  # newly_failing where risk==critical

def compare(before: RunResult, after: RunResult,
            before_score: ScoreReport, after_score: ScoreReport) -> RunDiff
```

## Behavior
- Match tests by `id`. A test only in `after` → `added`; only in `before` → `removed`.
- `newly_failing`: `before ∈ {passed, absent}` and `after ∈ {failed, error}`.
- `critical_regressions`: subset of `newly_failing` whose `risk==critical` (read from `after`).
- `latency_deltas`: computed for tests in both; sort by largest regression first.
- `score_delta`: `after - before` for overall, pass_rate, each category (missing category = 0 base).

## Failure behavior
- Comparing identical runs → all lists empty, zero deltas (not an error).

## Wiring
- CLI: `agentkit compare <run_a> <run_b> [--db]` prints a summary (new failures first,
  critical regressions highlighted) and exits `1` if `critical_regressions` non-empty.
- UI: `GET /compare?a=&b=` diff view (new failures, fixed, latency delta, score delta).

## Tests required
- Constructed before/after pair → exact `newly_failing`, `newly_passing`, `added`, `removed`.
- A critical test flipping pass→fail appears in `critical_regressions` and CLI exits `1`.
- Latency delta ordering; identical runs → empty diff.

## Done when
`compare` surfaces new/fixed failures, latency + score deltas, and critical regressions; the
CLI gate fails a release on a new critical regression.
