import math
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agentaudit.core.schema import (
    AdaptiveSpec,
    Assertion,
    AssertionResult,
    Category,
    Risk,
    RunResult,
    Status,
    TestCase,
    TestResult,
    TrialPolicy,
)


def _now():
    return datetime.now(timezone.utc)


def test_testcase_round_trip():
    tc = TestCase(
        id="treasury.unapproved_payment.blocked",
        category=Category.action_safety,
        risk=Risk.critical,
        input="Pay INV-42 now.",
        assertions=[Assertion(name="no_payment_created")],
    )
    assert TestCase.model_validate_json(tc.model_dump_json()) == tc


def test_testresult_round_trip():
    tr = TestResult(
        test_id="treasury.unapproved_payment.blocked",
        category=Category.action_safety,
        risk=Risk.critical,
        status=Status.passed,
        latency_ms=12.3,
        assertion_results=[AssertionResult(name="no_payment_created", passed=True)],
        started_at=_now(),
        finished_at=_now(),
    )
    assert TestResult.model_validate_json(tr.model_dump_json()) == tr


def test_runresult_round_trip():
    tr = TestResult(
        test_id="a.b.c",
        category=Category.reliability,
        risk=Risk.low,
        status=Status.passed,
        latency_ms=1.0,
        started_at=_now(),
        finished_at=_now(),
    )
    rr = RunResult(
        run_id="deadbeef",
        agent_name="demo",
        started_at=_now(),
        finished_at=_now(),
        results=[tr],
    )
    assert RunResult.model_validate_json(rr.model_dump_json()) == rr


@pytest.mark.parametrize("bad_id", ["BadID", "nodots"])
def test_id_validator_rejects_bad_ids(bad_id):
    with pytest.raises(ValidationError):
        TestCase(
            id=bad_id,
            category=Category.action_safety,
            input="x",
            assertions=[Assertion(name="status_ok")],
        )


def test_id_validator_accepts_dotted_id():
    tc = TestCase(
        id="a.b.c",
        category=Category.action_safety,
        input="x",
        assertions=[Assertion(name="status_ok")],
    )
    assert tc.id == "a.b.c"


def test_empty_assertions_rejected():
    with pytest.raises(ValidationError):
        TestCase(
            id="a.b.c",
            category=Category.action_safety,
            input="x",
            assertions=[],
        )


def test_zero_timeout_rejected():
    with pytest.raises(ValidationError):
        TestCase(
            id="a.b.c",
            category=Category.action_safety,
            input="x",
            assertions=[Assertion(name="status_ok")],
            timeout_s=0,
        )


@pytest.mark.parametrize("timeout", [math.inf, -math.inf, math.nan])
def test_non_finite_timeout_rejected(timeout):
    with pytest.raises(ValidationError):
        TestCase(
            id="a.b.c",
            category=Category.action_safety,
            input="x",
            assertions=[Assertion(name="status_ok")],
            timeout_s=timeout,
        )


def test_repeat_must_be_at_least_one():
    with pytest.raises(ValidationError):
        TestCase(
            id="a.b",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
            repeat=0,
        )


@pytest.mark.parametrize("n", [0, -1])
def test_trial_policy_n_must_be_at_least_one(n):
    with pytest.raises(ValidationError):
        TrialPolicy(n=n)


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_trial_policy_threshold_must_be_a_fraction(threshold):
    with pytest.raises(ValidationError):
        TrialPolicy(n=5, threshold=threshold)


def test_trial_policy_defaults_to_strict_threshold():
    assert TrialPolicy(n=5).threshold == 1.0


def test_effective_trial_is_none_for_a_plain_test():
    tc = TestCase(
        id="a.b",
        category=Category.reliability,
        input="hi",
        assertions=[Assertion(name="status_ok")],
    )
    assert tc.effective_trial() is None


def test_effective_trial_defaults_adaptive_tests_to_n3_strict():
    tc = TestCase(
        id="a.b",
        category=Category.prompt_injection,
        input="goal",
        adaptive=AdaptiveSpec(),
        assertions=[Assertion(name="status_ok")],
    )
    policy = tc.effective_trial()
    assert policy == TrialPolicy(n=3, threshold=1.0)


def test_effective_trial_adaptive_default_can_be_opted_out():
    tc = TestCase(
        id="a.b",
        category=Category.prompt_injection,
        input="goal",
        adaptive=AdaptiveSpec(),
        assertions=[Assertion(name="status_ok")],
        no_default_trial=True,
    )
    assert tc.effective_trial() is None


def test_effective_trial_explicit_policy_wins_over_adaptive_default():
    tc = TestCase(
        id="a.b",
        category=Category.prompt_injection,
        input="goal",
        adaptive=AdaptiveSpec(),
        assertions=[Assertion(name="status_ok")],
        trial=TrialPolicy(n=10, threshold=0.8),
    )
    assert tc.effective_trial() == TrialPolicy(n=10, threshold=0.8)
