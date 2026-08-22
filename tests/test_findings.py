"""The single definition of what failed, in what order, and why."""

from datetime import datetime, timezone

from agentaudit.core.findings import (
    detail_for,
    failed_assertions,
    failures,
    is_failure,
    order_by_failure,
)
from agentaudit.core.schema import AssertionResult, Category, Risk, Status, TestResult


def _result(test_id, status, *, assertions=(), error=None) -> TestResult:
    now = datetime.now(timezone.utc)
    return TestResult(
        test_id=test_id,
        category=Category.reliability,
        risk=Risk.low,
        status=status,
        latency_ms=1.0,
        assertion_results=list(assertions),
        error=error,
        started_at=now,
        finished_at=now,
    )


def test_an_error_counts_as_a_failure():
    # A test that could not run is not evidence the agent behaved.
    assert is_failure(_result("a", Status.error))
    assert is_failure(_result("a", Status.failed))
    assert not is_failure(_result("a", Status.passed))
    assert not is_failure(_result("a", Status.skipped))


def test_failures_come_first_and_skipped_last():
    ordered = order_by_failure(
        [
            _result("z.pass", Status.passed),
            _result("a.skip", Status.skipped),
            _result("m.error", Status.error),
            _result("b.fail", Status.failed),
        ]
    )

    assert [r.test_id for r in ordered] == ["b.fail", "m.error", "z.pass", "a.skip"]


def test_failures_filters_and_sorts_by_id():
    results = [
        _result("b.fail", Status.failed),
        _result("z.pass", Status.passed),
        _result("a.error", Status.error),
    ]

    assert [r.test_id for r in failures(results)] == ["a.error", "b.fail"]


def test_detail_is_the_first_failing_assertion_then_the_error():
    failing = _result(
        "a",
        Status.failed,
        assertions=[
            AssertionResult(name="first", passed=True, detail="fine"),
            AssertionResult(name="second", passed=False, detail="paid an unapproved invoice"),
            AssertionResult(name="third", passed=False, detail="also this"),
        ],
    )

    assert detail_for(failing) == "paid an unapproved invoice"
    assert [a.name for a in failed_assertions(failing)] == ["second", "third"]
    assert detail_for(_result("b", Status.error, error="timeout")) == "timeout"
    assert detail_for(_result("c", Status.passed)) == ""
