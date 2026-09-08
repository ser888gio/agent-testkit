"""Characterization baselines for PRD-004 tiered gating.

These pin the CURRENT single-tier behavior of `scoring.score` (and the
pass^k folding it consumes) so the upcoming blocking/reporting tier work
cannot silently drift the existing gate semantics.
"""

from datetime import datetime, timezone

from agentaudit.core.runner import _fold_attempts
from agentaudit.core.schema import (
    AssertionResult,
    Category,
    Risk,
    RunResult,
    Status,
    TestResult,
)
from agentaudit.core.scoring import score


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _result(category: Category, risk: Risk, status: Status) -> TestResult:
    return TestResult(
        test_id=f"{category}.{risk}.{status}",
        category=category,
        risk=risk,
        status=status,
        latency_ms=1.0,
        error="not applicable" if status is Status.skipped else None,
        started_at=_now(),
        finished_at=_now(),
    )


def _run(results: list[TestResult]) -> RunResult:
    return RunResult(
        run_id="r1",
        agent_name="a",
        started_at=_now(),
        finished_at=_now(),
        results=results,
    )


def test_baseline_empty_run_fails_closed() -> None:
    """Baseline: a run with no observed evidence never passes the gate."""
    report = score(_run([]))
    assert report.gate_passed is False
    assert report.incomplete is True
    assert report.overall_score == 0.0
    assert report.pass_rate == 0.0
    assert report.total == 0


def test_baseline_all_skipped_run_also_fails_closed() -> None:
    """Baseline: all-skipped is treated as empty evidence, not as absence of failure."""
    report = score(_run([_result(Category.reliability, Risk.low, Status.skipped)]))
    assert report.gate_passed is False
    assert report.incomplete is True


def test_baseline_critical_failure_blocks_regardless_of_weights() -> None:
    """Baseline: one critical failure blocks even when every weight favors passing."""
    results = [
        _result(Category.action_safety, Risk.critical, Status.failed),
        _result(Category.prompt_injection, Risk.low, Status.passed),
        _result(Category.performance, Risk.low, Status.passed),
    ]
    report = score(_run(results), fail_under=0.0)
    # The weighted score alone would clear any threshold at or below this...
    assert report.overall_score > 0.0
    assert report.critical_failures == 1
    # ...but the critical failure vetoes the gate.
    assert report.gate_passed is False

    # And the veto is the operator's `block_on_critical` setting, not automatic.
    report = score(_run(results), fail_under=0.0, block_on_critical=False)
    assert report.gate_passed is True


def test_baseline_fail_under_boundary_is_inclusive() -> None:
    """Baseline: overall_score == fail_under passes; anything below fails."""
    results = [
        _result(Category.reliability, Risk.low, Status.passed),
        _result(Category.reliability, Risk.low, Status.failed),
    ]
    at_threshold = score(_run(results), fail_under=0.5)
    assert at_threshold.overall_score == 0.5
    assert at_threshold.gate_passed is True

    below_threshold = score(_run(results), fail_under=0.5 + 1e-9)
    assert below_threshold.gate_passed is False


def test_baseline_flaky_folding_keeps_the_gate_verdict_of_the_folded_result() -> None:
    """Baseline: pass^k folding marks mixed attempts flaky; scoring counts but never gates on it.

    A folded result carries the first non-passing attempt's verdict plus its
    attempt list; `score` surfaces disagreement as `flaky` while the gate sees
    only the folded status.
    """

    def _attempt(status: Status, detail: str) -> TestResult:
        return TestResult(
            test_id="pk.case",
            category=Category.reliability,
            risk=Risk.medium,
            status=status,
            assertion_results=[AssertionResult(name="a", passed=False, detail=detail)],
            started_at=_now(),
            finished_at=_now(),
        )

    folded = _fold_attempts(
        [
            _attempt(Status.passed, "first"),
            _attempt(Status.failed, "second"),
            _attempt(Status.passed, "third"),
        ]
    )
    assert folded.status is Status.failed
    assert folded.attempts == [Status.passed, Status.failed, Status.passed]

    stable = _result(Category.reliability, Risk.low, Status.passed)
    report = score(_run([stable, folded]), fail_under=0.5)
    assert report.flaky == 1
    # The gate sees only the folded status (failed), not the 2/3 attempt spread;
    # `flaky` itself is reported-only and adds no separate veto.
    assert report.gate_passed is False
    green_but_flaky = score(
        _run([stable.model_copy(update={"attempts": [Status.passed, Status.passed]})])
    )
    assert green_but_flaky.flaky == 0


def test_baseline_weakest_category_signal_present_in_report() -> None:
    """Baseline: the weak-category quartile signal is always derivable from the report."""
    results = [_result(Category.prompt_injection, Risk.low, Status.passed) for _ in range(9)]
    results += [_result(Category.action_safety, Risk.low, Status.failed)]
    report = score(_run(results))

    assert report.weakest_category is Category.action_safety
    assert report.weak_category_score < 1.0
    # Reported, never gated on: the gate stays with the operator's threshold.
    assert report.gate_passed is True

    empty = score(_run([]))
    assert empty.weakest_category is None
    assert empty.weak_category_score == 1.0
