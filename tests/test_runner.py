import time

import agentkit.domains.treasury.sandbox  # noqa: F401 - registers the "treasury" sandbox
from agentkit.core.config import CallableSpec, TargetConfig
from agentkit.core.loader import PythonTestCase
from agentkit.core.redaction import EvidencePolicy
from agentkit.core.runner import run
from agentkit.core.schema import Assertion, Category, Risk, Status, TestCase

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


def test_sandbox_reset_isolation():
    cfg = TargetConfig(
        id="treasury-target",
        agent=CallableSpec(
            type="callable", callable="agentkit.domains.treasury.agent:create_agent"
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
            assertions=[
                Assertion(name="payment_created", args={"invoice_id": "INV-1"})
            ],
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
        assert False, "nope"

    def test_error(agent, sandbox):
        raise RuntimeError("kaboom")

    cfg = _target(f"{MODULE}:create_passing_agent")
    tests = [
        PythonTestCase(
            id="py.pass", category=Category.reliability, risk=Risk.low, fn=test_pass
        ),
        PythonTestCase(
            id="py.fail", category=Category.reliability, risk=Risk.low, fn=test_fail
        ),
        PythonTestCase(
            id="py.error", category=Category.reliability, risk=Risk.low, fn=test_error
        ),
    ]
    rr = run(cfg, tests)
    by_id = {r.test_id: r.status for r in rr.results}
    assert by_id["py.pass"] == Status.passed
    assert by_id["py.fail"] == Status.failed
    assert by_id["py.error"] == Status.error


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
