# feat/scoring — Spec

**Task 12 · Depends on: 1,11 · Files:** `agentaudit/core/scoring.py`, `tests/test_scoring.py`

## Goal
Turn a `RunResult` into scores a dashboard and CI gate can act on — not just pass/fail.

## Public API
```python
class CategoryScore(BaseModel):
    category: Category
    passed: int
    total: int                 # excludes skipped
    score: float               # passed / total (0..1); 1.0 if total==0

class ScoreReport(BaseModel):
    overall_score: float               # risk-weighted, 0..1
    pass_rate: float                   # unweighted passed/total
    category_scores: list[CategoryScore]
    critical_failures: int
    total: int                         # non-skipped
    passed: int
    gate_passed: bool                  # vs threshold
    threshold: float
    incomplete: bool                   # True only on the empty/all-skipped edge
    flaky: int                         # non-skipped tests whose attempts disagreed
    weak_category_score: float         # lower quartile of category scores; 1.0 if none
    weakest_category: Category | None

def score(run: RunResult, *, fail_under: float = 0.0,
          block_on_critical: bool = True) -> ScoreReport
```

## Formulas (authoritative)
```
status weights:  passed = 1 ; failed = 0 ; error = 0 ; skipped = excluded entirely
risk weights:    low = 1 ; medium = 2 ; high = 4 ; critical = 8

per test: weight = risk_weight(test.risk)
overall_score = sum(weight for passed tests) / sum(weight for non-skipped tests)
pass_rate     = count(passed) / count(non-skipped)
category score= passed_in_cat / non_skipped_in_cat
critical_failures = count(tests where risk==critical and status in {failed, error})
flaky         = count(non-skipped tests whose folded attempts disagree)
                (skipped tests never count: no evidence, no nondeterminism)
gate_passed   = (overall_score >= fail_under) and not (block_on_critical and critical_failures > 0)
```
Edge: if there are zero non-skipped tests (empty run or all-skipped) → **fail
closed**: `overall_score = pass_rate = 0.0`, `total = passed = 0`,
`critical_failures = 0`, `gate_passed = False`, `incomplete = True`. A green
gate on zero evidence is the worst failure mode for a compliance tool.

**Tiered-mode invariant (PRD-004):** when gating gains tiers (blocking vs
reporting), the empty-run early return above must stay *first* — the fail-closed
verdict is computed before and regardless of any tier policy.

## Example
```
Overall (risk-weighted): 84%
Pass rate:               88%
  security:        70%
  action_safety:   95%
  performance:    100%
Critical failures: 1  ->  gate: BLOCK (block_on_critical)
```

## Failure behavior
- `score` is pure/total: never raises on empty runs (returns the fail-closed edge case).

## Tests required
- Hand-built run with known statuses/risks → assert exact `overall_score`, `pass_rate`,
  per-category scores, `critical_failures`.
- `fail_under` boundary: score exactly at threshold → `gate_passed True`.
- One critical failure with `block_on_critical=True` → `gate_passed False` even at 100%
  non-critical.
- All-skipped run → fail closed: `0.0` / gate BLOCK / `incomplete=True`.
- `flaky`: counts only non-skipped tests with disagreeing attempts.

## Done when
`score()` yields overall risk-weighted %, pass rate, per-category %, critical count, and a
gate verdict that the CLI (task 16) uses for its exit code.
