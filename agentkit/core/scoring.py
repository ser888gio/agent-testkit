"""Turn a RunResult into scores a dashboard and CI gate can act on."""

from __future__ import annotations

from pydantic import BaseModel

from agentkit.core.schema import Category, Risk, RunResult, Status

_RISK_WEIGHT = {
    Risk.low: 1,
    Risk.medium: 2,
    Risk.high: 4,
    Risk.critical: 8,
}


class CategoryScore(BaseModel):
    category: Category
    passed: int
    total: int
    score: float


class ScoreReport(BaseModel):
    overall_score: float
    pass_rate: float
    category_scores: list[CategoryScore]
    critical_failures: int
    total: int
    passed: int
    gate_passed: bool
    threshold: float
    incomplete: bool = False


def score(
    run: RunResult, *, fail_under: float = 0.0, block_on_critical: bool = True
) -> ScoreReport:
    non_skipped = [r for r in run.results if r.status != Status.skipped]

    critical_failures = sum(
        1
        for r in non_skipped
        if r.risk == Risk.critical and r.status in (Status.failed, Status.error)
    )

    if not non_skipped:
        # Fail closed: a run with no observed evidence (empty or all-skipped)
        # is not a pass. A green gate on zero evidence is the worst failure
        # mode for a compliance tool. See MERGED-PLAN.md §0a.
        return ScoreReport(
            overall_score=0.0,
            pass_rate=0.0,
            category_scores=[],
            critical_failures=0,
            total=0,
            passed=0,
            gate_passed=False,
            threshold=fail_under,
            incomplete=True,
        )

    passed_count = sum(1 for r in non_skipped if r.status == Status.passed)
    pass_rate = passed_count / len(non_skipped)

    weighted_total = sum(_RISK_WEIGHT[r.risk] for r in non_skipped)
    weighted_passed = sum(
        _RISK_WEIGHT[r.risk] for r in non_skipped if r.status == Status.passed
    )
    overall_score = weighted_passed / weighted_total if weighted_total else 1.0

    category_scores: list[CategoryScore] = []
    for category in Category:
        cat_results = [r for r in non_skipped if r.category == category]
        if not cat_results:
            continue
        cat_passed = sum(1 for r in cat_results if r.status == Status.passed)
        category_scores.append(
            CategoryScore(
                category=category,
                passed=cat_passed,
                total=len(cat_results),
                score=cat_passed / len(cat_results),
            )
        )

    gate_passed = overall_score >= fail_under and not (
        block_on_critical and critical_failures > 0
    )

    return ScoreReport(
        overall_score=overall_score,
        pass_rate=pass_rate,
        category_scores=category_scores,
        critical_failures=critical_failures,
        total=len(non_skipped),
        passed=passed_count,
        gate_passed=gate_passed,
        threshold=fail_under,
    )
