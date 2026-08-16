import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import agentaudit.domains.treasury.sandbox  # noqa: F401 - registers the "treasury" sandbox
from agentaudit.core.config import CallableSpec, TargetConfig
from agentaudit.core.loader import PythonTestCase
from agentaudit.core.redaction import EvidencePolicy
from agentaudit.core.runner import _fold_attempts, run
from agentaudit.core.schema import (
    Assertion,
    AssertionResult,
    Category,
    Risk,
    Status,
    TestCase,
    TestResult,
)

MODULE = "tests.test_runner"


def _passing_agent(input: str) -> str:
    return "ok everything approved"


def _slow_agent(input: str) -> str:
    time.sleep(2)
    return "too slow"


def create_passing_agent():
    return _passing_agent


def create_slow_agent():
    return _slow_agent


def _target(callable_ref: str, evidence: EvidencePolicy | None = None) -> TargetConfig:
    return TargetConfig(
        id="test-target",
        agent=CallableSpec(type="callable", callable=callable_ref),
        sandbox=None,
        evidence=evidence or EvidencePolicy(),
    )


def test_mixed_pack_statuses():
    cfg = _target(f"{MODULE}:create_passing_agent")
    tests = [
        TestCase(
            id="a.pass.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="contains_any", args={"values": ["ok"]})],
        ),
        TestCase(
            id="b.fail.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="contains_any", args={"values": ["nope"]})],
        ),
        TestCase(
            id="c.skip.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
            tags=["skip"],
        ),
    ]
    rr = run(cfg, tests)
    by_id = {r.test_id: r.status for r in rr.results}
    assert by_id["a.pass.case"] == Status.passed
    assert by_id["b.fail.case"] == Status.failed
    assert by_id["c.skip.case"] == Status.skipped


def test_erroring_agent_yields_error_status():
    def _boom(input):
        raise RuntimeError("agent exploded")

    cfg = TargetConfig(
        id="err-target",
        agent=CallableSpec(type="callable", callable=f"{MODULE}:_boom_factory"),
    )
    tests = [
        TestCase(
            id="a.err.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        )
    ]
    rr = run(cfg, tests)
    assert rr.results[0].status == Status.error


def _boom_factory():
    def _boom(input):
        raise RuntimeError("agent exploded")

    return _boom


def test_timeout_yields_error():
    cfg = _target(f"{MODULE}:create_slow_agent")
    tests = [
        TestCase(
            id="a.slow.case",
            category=Category.performance,
            input="hi",
            assertions=[Assertion(name="status_ok")],
            timeout_s=0.1,
        )
    ]
    rr = run(cfg, tests)
    assert rr.results[0].status == Status.error
    assert rr.results[0].error == "timeout"


def _paying_then_hanging_agent(input, sandbox):
    sandbox.bank.create_payment("INV-9", 100, "ACME", "DE00")
    time.sleep(30)
    return "never returned"


def create_paying_then_hanging_agent():
    return _paying_then_hanging_agent


def test_timeout_still_yields_a_trustworthy_diff():
    # The side effect landed before the agent hung. Isolation destroys the
    # process holding the orphan, so the snapshot at the timeout instant is
    # final evidence rather than a racy read.
    cfg = TargetConfig(
        id="hang-target",
        agent=CallableSpec(type="callable", callable=f"{MODULE}:create_paying_then_hanging_agent"),
        sandbox="treasury",
    )
    tests = [
        TestCase(
            id="hang.case",
            category=Category.action_safety,
            input="Pay INV-9",
            assertions=[Assertion(name="payment_created", args={"invoice_id": "INV-9"})],
            timeout_s=0.5,
        )
    ]
    result = run(cfg, tests).results[0]
    assert result.status == Status.error
    assert result.error == "timeout"
    assert result.sandbox_diff is not None
    assert result.sandbox_diff["changed"]["payments"]["after"]


def _suicidal_agent(input):
    os._exit(1)


def create_suicidal_agent():
    return _suicidal_agent


def test_dead_child_becomes_an_error_not_an_exception():
    cfg = _target(f"{MODULE}:create_suicidal_agent")
    tests = [
        TestCase(
            id="dead.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        ),
        TestCase(
            id="after.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        ),
    ]
    rr = run(cfg, tests)
    # Both error, and the run itself still completes: a dead child is recycled.
    assert [r.status for r in rr.results] == [Status.error, Status.error]


def _forking_hanging_agent(input):
    started = f"{input}.started"
    survived = f"{input}.survived"
    code = (
        "import pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text('started'); "
        "time.sleep(2); "
        "pathlib.Path(sys.argv[2]).write_text('survived')"
    )
    subprocess.Popen(
        [sys.executable, "-c", code, started, survived],
        close_fds=True,
    )
    deadline = time.monotonic() + 0.8
    while not Path(started).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(30)
    return "never returned"


def create_forking_hanging_agent():
    return _forking_hanging_agent


def test_timeout_kills_agent_descendants(tmp_path):
    marker = tmp_path / "agent-child"
    cfg = _target(f"{MODULE}:create_forking_hanging_agent")
    test = TestCase(
        id="tree.timeout.case",
        category=Category.reliability,
        input=str(marker),
        assertions=[Assertion(name="status_ok")],
        timeout_s=1.0,
    )

    result = run(cfg, [test]).results[0]
    assert result.error == "timeout"
    assert Path(f"{marker}.started").exists()
    time.sleep(2.5)
    assert not Path(f"{marker}.survived").exists()


def test_sandbox_reset_isolation():
    cfg = TargetConfig(
        id="treasury-target",
        agent=CallableSpec(
            type="callable", callable="agentaudit.domains.treasury.agent:create_agent"
        ),
        sandbox="treasury",
    )
    invoice = {
        "id": "INV-1",
        "amount": 100,
        "approved": True,
        "payee": "ACME",
        "bank_details": "DE00",
    }
    tests = [
        TestCase(
            id="pay.first",
            category=Category.action_safety,
            input="Pay invoice INV-1 now.",
            setup={"invoices": [invoice]},
            assertions=[Assertion(name="payment_created", args={"invoice_id": "INV-1"})],
        ),
        TestCase(
            id="pay.second_should_be_clean",
            category=Category.action_safety,
            input="What's the status of INV-1?",
            setup={},
            assertions=[Assertion(name="no_payment_created")],
        ),
    ]
    rr = run(cfg, tests)
    assert rr.results[0].status == Status.passed
    assert rr.results[1].status == Status.passed
    assert rr.results[1].sandbox_diff["added"] == {}
    assert rr.results[1].sandbox_diff["changed"] == {}


def test_evidence_store_response_false():
    cfg = _target(
        f"{MODULE}:create_passing_agent",
        evidence=EvidencePolicy(store_response=False),
    )
    tests = [
        TestCase(
            id="a.evidence.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        )
    ]
    rr = run(cfg, tests)
    assert rr.results[0].response is None


def test_evidence_request_redacted():
    cfg = _target(f"{MODULE}:create_passing_agent")
    tests = [
        TestCase(
            id="a.secret.case",
            category=Category.reliability,
            input="my key is sk-abcdefgh12345678",
            assertions=[Assertion(name="status_ok")],
        )
    ]
    rr = run(cfg, tests)
    assert "sk-abcdefgh12345678" not in rr.results[0].request


def test_python_testcase_pass_fail_error():
    def test_pass(agent, sandbox):
        assert True

    def test_fail(agent, sandbox):
        raise AssertionError("nope")

    def test_error(agent, sandbox):
        raise RuntimeError("kaboom")

    cfg = _target(f"{MODULE}:create_passing_agent")
    tests = [
        PythonTestCase(id="py.pass", category=Category.reliability, risk=Risk.low, fn=test_pass),
        PythonTestCase(id="py.fail", category=Category.reliability, risk=Risk.low, fn=test_fail),
        PythonTestCase(id="py.error", category=Category.reliability, risk=Risk.low, fn=test_error),
    ]
    rr = run(cfg, tests)
    by_id = {r.test_id: r.status for r in rr.results}
    assert by_id["py.pass"] == Status.passed
    assert by_id["py.fail"] == Status.failed
    assert by_id["py.error"] == Status.error


def test_python_testcase_timeout_is_killable():
    def test_hangs(agent, sandbox):
        time.sleep(30)

    cfg = _target(f"{MODULE}:create_passing_agent")
    test = PythonTestCase(
        id="py.timeout",
        category=Category.reliability,
        risk=Risk.medium,
        fn=test_hangs,
        timeout_s=0.1,
    )

    started = time.monotonic()
    result = run(cfg, [test]).results[0]
    assert time.monotonic() - started < 10
    assert result.status == Status.error
    assert result.error == "timeout"


def test_unserializable_test_input_becomes_error_result():
    cfg = _target(f"{MODULE}:create_passing_agent")
    test = TestCase(
        id="ipc.serialization.case",
        category=Category.reliability,
        input={"generator": (value for value in range(1))},
        assertions=[Assertion(name="status_ok")],
    )

    result = run(cfg, [test]).results[0]
    assert result.status == Status.error
    assert "pickle" in result.error.lower()


_TURNS_SEEN: list[str] = []


def _recording_agent(input: str) -> str:
    _TURNS_SEEN.append(input)
    return " | ".join(_TURNS_SEEN)


def create_recording_agent():
    _TURNS_SEEN.clear()
    return _recording_agent


def test_multi_turn_feeds_turns_in_order_without_reset():
    # The agent echoes every turn it has seen; asserting on the final response
    # proves both turns arrived, in order, with state carried across turns.
    cfg = _target(f"{MODULE}:create_recording_agent")
    tests = [
        TestCase(
            id="mt.memory.case",
            category=Category.memory_context,
            turns=["INV-77 is pre-approved", "Pay INV-77"],
            assertions=[
                Assertion(
                    name="contains_any",
                    args={"values": ["pre-approved | Pay INV-77"]},
                )
            ],
        )
    ]
    rr = run(cfg, tests)
    result = rr.results[0]
    assert result.status == Status.passed
    # Request evidence records both turns, not a single input.
    assert result.request == ["INV-77 is pre-approved", "Pay INV-77"]


def test_single_input_test_unchanged_by_multi_turn_support():
    cfg = _target(f"{MODULE}:create_passing_agent")
    tests = [
        TestCase(
            id="si.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="contains_any", args={"values": ["ok"]})],
        )
    ]
    rr = run(cfg, tests)
    assert rr.results[0].status == Status.passed
    assert rr.results[0].request == "hi"


def test_repeat_folds_attempts_into_one_result():
    cfg = _target(f"{MODULE}:create_passing_agent")
    tests = [
        TestCase(
            id="pk.stable.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="contains_any", args={"values": ["ok"]})],
            repeat=3,
        )
    ]
    rr = run(cfg, tests)
    assert len(rr.results) == 1
    assert rr.results[0].status == Status.passed
    assert rr.results[0].attempts == [Status.passed] * 3


def test_repeat_one_leaves_attempts_empty():
    cfg = _target(f"{MODULE}:create_passing_agent")
    tests = [
        TestCase(
            id="pk.single.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="contains_any", args={"values": ["ok"]})],
        )
    ]
    rr = run(cfg, tests)
    assert rr.results[0].attempts == []


def test_fold_attempts_fails_on_any_failing_attempt():
    def _attempt(status, detail):
        return TestResult(
            test_id="pk.case",
            category=Category.reliability,
            risk=Risk.medium,
            status=status,
            assertion_results=[AssertionResult(name="a", passed=False, detail=detail)],
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

    folded = _fold_attempts(
        [
            _attempt(Status.passed, "first"),
            _attempt(Status.failed, "second"),
            _attempt(Status.passed, "third"),
        ]
    )
    assert folded.status == Status.failed
    assert folded.attempts == [Status.passed, Status.failed, Status.passed]
    # Evidence comes from the first non-passing attempt, so it explains the verdict.
    assert folded.assertion_results[0].detail == "second"

    errored = _fold_attempts([_attempt(Status.error, "boom"), _attempt(Status.passed, "ok")])
    assert errored.status == Status.error
