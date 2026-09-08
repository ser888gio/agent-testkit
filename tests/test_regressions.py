from datetime import datetime, timezone

from agentaudit.core.regressions import compare, detect_error_rate_incident
from agentaudit.core.schema import Category, Risk, RunResult, Status, TestResult
from agentaudit.core.scoring import score


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
        run_id="r",
        agent_name="a",
        started_at=_now(),
        finished_at=_now(),
        results=results,
    )


def test_newly_failing_newly_passing_added_removed():
    before = _run(
        [
            _tr("a.stays_pass", Category.reliability, Risk.low, Status.passed),
            _tr(
                "b.was_pass_now_fail", Category.action_safety, Risk.high, Status.passed
            ),
            _tr(
                "c.was_fail_now_pass", Category.reliability, Risk.medium, Status.failed
            ),
            _tr("d.stays_fail", Category.performance, Risk.low, Status.failed),
            _tr("e.removed", Category.reliability, Risk.low, Status.passed),
        ]
    )
    after = _run(
        [
            _tr("a.stays_pass", Category.reliability, Risk.low, Status.passed),
            _tr(
                "b.was_pass_now_fail", Category.action_safety, Risk.high, Status.failed
            ),
            _tr(
                "c.was_fail_now_pass", Category.reliability, Risk.medium, Status.passed
            ),
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
            _tr(
                "x.slower",
                Category.performance,
                Risk.low,
                Status.passed,
                latency_ms=100,
            ),
            _tr(
                "y.faster",
                Category.performance,
                Risk.low,
                Status.passed,
                latency_ms=100,
            ),
        ]
    )
    after = _run(
        [
            _tr(
                "x.slower",
                Category.performance,
                Risk.low,
                Status.passed,
                latency_ms=500,
            ),
            _tr(
                "y.faster", Category.performance, Risk.low, Status.passed, latency_ms=50
            ),
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


def _run_with(statuses) -> RunResult:
    return RunResult(
        run_id="r",
        agent_name="a",
        started_at=_now(),
        finished_at=_now(),
        results=[
            _tr(f"t.{i}", Category.reliability, Risk.low, s) for i, s in enumerate(statuses)
        ],
    )


ALL_ERROR = [Status.error] * 4
ALL_PASS = [Status.passed] * 4


def test_error_rate_spike_against_a_clean_baseline():
    incident = detect_error_rate_incident(_run_with(ALL_ERROR), [0.0, 0.0, 0.0, 0.1])

    assert incident is not None
    assert incident.error_rate == 1.0
    assert incident.baseline == 0.0
    assert incident.no_baseline is False
    assert (incident.errored, incident.total) == (4, 4)


def test_a_target_that_always_errors_is_not_a_spike():
    # Chronically broken is a different problem from newly broken, and firing
    # every run would make the flag noise.
    assert detect_error_rate_incident(_run_with(ALL_ERROR), [1.0, 1.0, 1.0, 1.0]) is None


def test_first_run_erroring_outright_is_flagged_without_a_baseline():
    # The shape the 4 Sep railway cluster actually has: an agent's first run
    # errors on every test, then recovers once configured. A pure jump rule
    # would miss it -- there is no history to jump from.
    incident = detect_error_rate_incident(_run_with(ALL_ERROR), [])

    assert incident is not None
    assert incident.no_baseline is True
    assert incident.baseline is None


def test_a_healthy_run_is_not_an_incident():
    assert detect_error_rate_incident(_run_with(ALL_PASS), [0.0, 0.0, 0.0]) is None
    # ...and neither is a run that merely failed: a failure is a verdict.
    assert detect_error_rate_incident(_run_with([Status.failed] * 4), [0.0, 0.0, 0.0]) is None


def test_a_moderate_error_rate_stays_below_the_floor():
    # 1 in 4 errored: the score is still computed on a majority of the suite.
    assert detect_error_rate_incident(
        _run_with([Status.error, *[Status.passed] * 3]), [0.0, 0.0, 0.0]
    ) is None


def test_empty_run_is_not_an_incident():
    assert detect_error_rate_incident(_run_with([]), [0.0, 0.0, 0.0]) is None
