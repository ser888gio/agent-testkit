from datetime import datetime, timezone

from agentkit.core.regressions import compare
from agentkit.core.schema import Category, Risk, RunResult, Status, TestResult
from agentkit.core.scoring import score


def _now():
    return datetime.now(timezone.utc)


def _tr(test_id, category, risk, status, latency_ms=10.0) -> TestResult:
    return TestResult(
        test_id=test_id,
        category=category,
        risk=risk,
        status=status,
        latency_ms=latency_ms,
        started_at=_now(),
        finished_at=_now(),
    )


def _run(results) -> RunResult:
    return RunResult(
        run_id="r", agent_name="a", started_at=_now(), finished_at=_now(), results=results
    )


def test_newly_failing_newly_passing_added_removed():
    before = _run(
        [
            _tr("a.stays_pass", Category.reliability, Risk.low, Status.passed),
            _tr("b.was_pass_now_fail", Category.action_safety, Risk.high, Status.passed),
            _tr("c.was_fail_now_pass", Category.reliability, Risk.medium, Status.failed),
            _tr("d.stays_fail", Category.performance, Risk.low, Status.failed),
            _tr("e.removed", Category.reliability, Risk.low, Status.passed),
        ]
    )
    after = _run(
        [
            _tr("a.stays_pass", Category.reliability, Risk.low, Status.passed),
            _tr("b.was_pass_now_fail", Category.action_safety, Risk.high, Status.failed),
            _tr("c.was_fail_now_pass", Category.reliability, Risk.medium, Status.passed),
            _tr("d.stays_fail", Category.performance, Risk.low, Status.error),
            _tr("f.added", Category.reliability, Risk.low, Status.passed),
        ]
    )

    diff = compare(before, after, score(before), score(after))

    assert diff.newly_failing == ["b.was_pass_now_fail"]
    assert diff.newly_passing == ["c.was_fail_now_pass"]
    assert diff.still_failing == ["d.stays_fail"]
    assert diff.added == ["f.added"]
    assert diff.removed == ["e.removed"]


def test_critical_regression_flagged():
    before = _run(
        [_tr("crit.test", Category.action_safety, Risk.critical, Status.passed)]
    )
    after = _run(
        [_tr("crit.test", Category.action_safety, Risk.critical, Status.failed)]
    )
    diff = compare(before, after, score(before), score(after))
    assert diff.newly_failing == ["crit.test"]
    assert diff.critical_regressions == ["crit.test"]


def test_latency_delta_ordering_largest_regression_first():
    before = _run(
        [
            _tr("x.slower", Category.performance, Risk.low, Status.passed, latency_ms=100),
            _tr("y.faster", Category.performance, Risk.low, Status.passed, latency_ms=100),
        ]
    )
    after = _run(
        [
            _tr("x.slower", Category.performance, Risk.low, Status.passed, latency_ms=500),
            _tr("y.faster", Category.performance, Risk.low, Status.passed, latency_ms=50),
        ]
    )
    diff = compare(before, after, score(before), score(after))
    assert [d.test_id for d in diff.latency_deltas] == ["x.slower", "y.faster"]


def test_score_delta_overall_and_category():
    before = _run(
        [
            _tr("a", Category.reliability, Risk.low, Status.passed),
            _tr("b", Category.reliability, Risk.low, Status.failed),
        ]
    )
    after = _run(
        [
            _tr("a", Category.reliability, Risk.low, Status.passed),
            _tr("b", Category.reliability, Risk.low, Status.passed),
        ]
    )
    diff = compare(before, after, score(before), score(after))
    assert diff.score_delta["overall"] > 0
    assert diff.score_delta["pass_rate"] > 0
    assert diff.score_delta["reliability"] > 0


def test_identical_runs_empty_diff():
    run = _run(
        [
            _tr("a", Category.reliability, Risk.low, Status.passed),
            _tr("b", Category.action_safety, Risk.critical, Status.failed),
        ]
    )
    diff = compare(run, run, score(run), score(run))
    assert diff.newly_failing == []
    assert diff.newly_passing == []
    assert diff.added == []
    assert diff.removed == []
    assert diff.critical_regressions == []
    assert diff.score_delta["overall"] == 0.0
    assert diff.score_delta["pass_rate"] == 0.0
