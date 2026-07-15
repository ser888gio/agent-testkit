from datetime import datetime, timezone

from agentkit.core.schema import Category, Risk, RunResult, Status, TestResult
from agentkit.core.scoring import score


def _now():
    return datetime.now(timezone.utc)


def _result(category, risk, status) -> TestResult:
    return TestResult(
        test_id=f"{category}.{risk}.{status}",
        category=category,
        risk=risk,
        status=status,
        latency_ms=1.0,
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


def test_known_run_expected_numbers():
    results = [
        _result(Category.action_safety, Risk.critical, Status.passed),
        _result(Category.action_safety, Risk.high, Status.failed),
        _result(Category.performance, Risk.low, Status.passed),
        _result(Category.performance, Risk.medium, Status.passed),
    ]
    rr = _run(results)
    report = score(rr)

    # weighted: passed weights = 8 + 1 + 2 = 11; total weights = 8+4+1+2 = 15
    assert report.overall_score == 11 / 15
    assert report.pass_rate == 3 / 4
    assert report.total == 4
    assert report.passed == 3
    assert report.critical_failures == 0

    by_cat = {c.category: c for c in report.category_scores}
    assert by_cat[Category.action_safety].passed == 1
    assert by_cat[Category.action_safety].total == 2
    assert by_cat[Category.action_safety].score == 0.5
    assert by_cat[Category.performance].score == 1.0


def test_fail_under_boundary_exact_threshold_passes():
    results = [
        _result(Category.reliability, Risk.low, Status.passed),
        _result(Category.reliability, Risk.low, Status.failed),
    ]
    rr = _run(results)
    report = score(rr, fail_under=0.5)
    assert report.overall_score == 0.5
    assert report.gate_passed is True


def test_critical_failure_blocks_gate_even_at_high_score():
    results = [
        _result(Category.action_safety, Risk.critical, Status.failed),
        _result(Category.performance, Risk.low, Status.passed),
        _result(Category.performance, Risk.low, Status.passed),
    ]
    rr = _run(results)
    report = score(rr, fail_under=0.0, block_on_critical=True)
    assert report.critical_failures == 1
    assert report.gate_passed is False


def test_critical_failure_does_not_block_when_disabled():
    results = [_result(Category.action_safety, Risk.critical, Status.failed)]
    rr = _run(results)
    report = score(rr, fail_under=0.0, block_on_critical=False)
    assert report.gate_passed is True


def test_all_skipped_run_edge_case():
    results = [_result(Category.reliability, Risk.low, Status.skipped)]
    rr = _run(results)
    report = score(rr)
    assert report.overall_score == 1.0
    assert report.pass_rate == 1.0
    assert report.gate_passed is True
    assert report.total == 0


def test_error_status_counts_as_failure_weight():
    results = [
        _result(Category.reliability, Risk.high, Status.error),
        _result(Category.reliability, Risk.high, Status.passed),
    ]
    rr = _run(results)
    report = score(rr)
    assert report.overall_score == 0.5
    assert report.pass_rate == 0.5
