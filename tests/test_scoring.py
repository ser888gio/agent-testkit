from datetime import datetime, timezone

import pytest

from agentaudit.core.schema import Category, Risk, RunResult, Status, TestResult
from agentaudit.core.scoring import score


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


def test_all_skipped_run_fails_closed():
    # A run with no observed evidence must not pass the gate. See MERGED-PLAN §0a.
    results = [_result(Category.reliability, Risk.low, Status.skipped)]
    rr = _run(results)
    report = score(rr)
    assert report.overall_score == 0.0
    assert report.pass_rate == 0.0
    assert report.gate_passed is False
    assert report.incomplete is True
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


def test_flaky_counts_only_tests_with_mixed_attempts():
    stable = _result(Category.reliability, Risk.low, Status.passed)
    consistent = stable.model_copy(
        update={"test_id": "consistent", "attempts": [Status.passed] * 3}
    )
    mixed = stable.model_copy(
        update={
            "test_id": "mixed",
            "status": Status.failed,
            "attempts": [Status.passed, Status.failed, Status.passed],
        }
    )
    report = score(_run([stable, consistent, mixed]))
    assert report.flaky == 1


def test_flaky_ignores_skipped_tests():
    # A skipped test carries no observed evidence, so its attempt history --
    # however it came to be -- cannot witness nondeterminism.
    stable = _result(Category.reliability, Risk.low, Status.passed)
    skipped = _result(Category.reliability, Risk.low, Status.skipped).model_copy(
        update={"test_id": "skipped.mixed", "attempts": [Status.passed, Status.failed]}
    )
    report = score(_run([stable, skipped]))
    assert report.flaky == 0
    assert report.total == 1


# The overall score averages a bad category away; the weak-category signal is
# what an assurance reader actually needs to see.
def test_weakest_category_is_reported_even_when_the_overall_score_is_high():
    results = [_result(Category.prompt_injection, Risk.low, Status.passed) for _ in range(9)]
    results += [_result(Category.action_safety, Risk.low, Status.failed) for _ in range(3)]
    report = score(_run(results))

    assert report.overall_score > 0.7  # looks healthy on its own
    assert report.weakest_category is Category.action_safety
    # Two categories at 1.0 and 0.0: the quartile interpolates rather than
    # collapsing to the minimum, so the number stays well below the overall
    # score without claiming the whole run is a zero.
    assert report.weak_category_score < 0.5


def test_weak_category_score_is_the_lower_quartile_not_the_minimum():
    # Three categories at 1.0, 1.0 and 0.5: the lower quartile sits between the
    # worst and the rest, so a single soft category does not read as a zero.
    results = [
        _result(Category.prompt_injection, Risk.low, Status.passed),
        _result(Category.data_leakage, Risk.low, Status.passed),
        _result(Category.tool_use, Risk.low, Status.passed),
        _result(Category.tool_use, Risk.low, Status.failed),
    ]
    report = score(_run(results))

    assert report.weakest_category is Category.tool_use
    assert 0.5 < report.weak_category_score < 1.0


def test_a_uniformly_passing_run_has_no_weak_category():
    results = [
        _result(Category.prompt_injection, Risk.low, Status.passed),
        _result(Category.data_leakage, Risk.low, Status.passed),
    ]
    report = score(_run(results))
    assert report.weak_category_score == pytest.approx(1.0)


def test_an_empty_run_reports_no_weakest_category():
    report = score(_run([]))
    assert report.weakest_category is None
    assert report.incomplete is True


def test_the_weak_category_signal_does_not_move_the_gate():
    # One broken category, everything else clean, threshold below the overall
    # score: the gate is the operator's setting and must not shift under them.
    results = [_result(Category.prompt_injection, Risk.low, Status.passed) for _ in range(9)]
    results += [_result(Category.action_safety, Risk.low, Status.failed)]
    report = score(_run(results), fail_under=0.5)

    assert report.weak_category_score < 0.5
    assert report.gate_passed is True


def test_all_errored_run_fails_closed():
    # Same condition as the all-skipped run above: nothing passed, and an error
    # is the absence of a verdict rather than a lenient one. With the default
    # fail_under of 0.0 this would otherwise gate green on zero evidence.
    rr = _run([_result(Category.reliability, Risk.high, Status.error)])
    report = score(rr)
    assert report.gate_passed is False
    assert report.incomplete is True


def test_zero_passed_with_a_mix_of_errors_and_failures_fails_closed():
    rr = _run(
        [
            _result(Category.reliability, Risk.high, Status.error),
            _result(Category.tool_use, Risk.low, Status.failed),
        ]
    )
    report = score(rr)
    assert report.gate_passed is False
    assert report.incomplete is True


def test_a_cleanly_failed_run_is_a_verdict_not_missing_evidence():
    # No errors: every test produced a real result. That is a normal BLOCK at a
    # meaningful threshold, and must not be relabelled INCOMPLETE.
    rr = _run([_result(Category.reliability, Risk.high, Status.failed)])
    report = score(rr, fail_under=0.8)
    assert report.gate_passed is False
    assert report.incomplete is False


def test_any_passing_evidence_keeps_existing_gate_semantics():
    # Deliberately narrow: one error alongside a pass leaves the gate exactly
    # where it was, so this does not silently block existing users' runs.
    rr = _run(
        [
            _result(Category.reliability, Risk.high, Status.error),
            _result(Category.tool_use, Risk.high, Status.passed),
        ]
    )
    report = score(rr)
    assert report.gate_passed is True
    assert report.incomplete is False


def test_verdict_rate_gates_a_high_scoring_but_uncovered_run():
    # One passing verdict among three tests: perfect score, 1/3 coverage.
    results = [
        _result(Category.action_safety, Risk.high, Status.passed),
        _result(Category.tool_use, Risk.high, Status.skipped),
        _result(Category.data_leakage, Risk.high, Status.error),
    ]
    rr = _run(results)

    assert score(rr).verdict_rate == pytest.approx(1 / 3)
    assert score(rr, min_verdict_rate=0.0).gate_passed is True
    assert score(rr, min_verdict_rate=0.8).gate_passed is False
    # Boundary: exactly meeting the floor passes, like `fail_under`.
    assert score(rr, min_verdict_rate=1 / 3).gate_passed is True


def test_verdict_rate_counts_failures_as_coverage():
    results = [
        _result(Category.action_safety, Risk.low, Status.passed),
        _result(Category.tool_use, Risk.low, Status.failed),
    ]
    report = score(_run(results), min_verdict_rate=1.0)
    assert report.verdict_rate == 1.0
    assert report.gate_passed is True
