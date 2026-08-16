from datetime import datetime, timezone

from agentaudit.core.config import CallableSpec, HTTPSpec, TargetConfig
from agentaudit.core.discovery import (
    ECHO_PROBE,
    MEMORY_PHRASE,
    MEMORY_PROBE,
    PROBES,
    discover,
    profile_from_config,
)
from agentaudit.core.schema import Category, Risk, RunResult, Status, TestResult

MODULE = "tests.test_discovery"


def create_stateless_agent():
    return lambda input: "READY"


def _target(sandbox=None, http=False):
    agent = (
        HTTPSpec(
            type="http",
            endpoint="https://agent.example/chat",
            request={"input": "{{ input }}"},
        )
        if http
        else CallableSpec(type="callable", callable=f"{MODULE}:create_stateless_agent")
    )
    return TargetConfig(id="probe-target", agent=agent, sandbox=sandbox)


def _fake_runner(statuses: dict[str, Status], latency: float | None = 12.0):
    now = datetime.now(timezone.utc)

    def _run(config, tests):
        return RunResult(
            run_id="r1",
            agent_name=config.id,
            started_at=now,
            finished_at=now,
            results=[
                TestResult(
                    test_id=t.id,
                    category=t.category,
                    risk=t.risk,
                    status=statuses[t.id],
                    latency_ms=latency,
                    started_at=now,
                    finished_at=now,
                )
                for t in tests
            ],
        )

    return _run


def test_probes_are_cheap_and_only_two():
    assert [p.id for p in PROBES] == [ECHO_PROBE, MEMORY_PROBE]
    assert all(p.timeout_s <= 15 for p in PROBES)
    assert MEMORY_PHRASE in PROBES[1].turns[0]


def test_offline_profile_reads_the_target_config():
    treasury = profile_from_config(_target(sandbox="treasury"))
    assert treasury.domain == "treasury"
    assert treasury.tool_use is True
    assert treasury.risk_level is Risk.critical
    assert "money_movement" in treasury.side_effects

    plain = profile_from_config(_target())
    assert plain.domain == "generic"
    assert plain.tool_use is False
    assert plain.risk_level is Risk.medium

    assert profile_from_config(_target(http=True)).structured_input is True


def test_discovery_marks_a_stateless_agent_stateless():
    profile = discover(
        _target(),
        runner=_fake_runner({ECHO_PROBE: Status.passed, MEMORY_PROBE: Status.failed}),
    )

    assert profile.multi_turn is False
    assert any("stateless" in note for note in profile.notes)
    assert any("12 ms" in note for note in profile.notes)


def test_discovery_detects_carried_context():
    profile = discover(
        _target(),
        runner=_fake_runner({ECHO_PROBE: Status.passed, MEMORY_PROBE: Status.passed}),
    )

    assert profile.multi_turn is True
    assert any("across two turns" in note for note in profile.notes)


def test_an_unreachable_endpoint_does_not_get_a_multi_turn_claim():
    profile = discover(
        _target(),
        runner=_fake_runner({ECHO_PROBE: Status.error, MEMORY_PROBE: Status.error}),
    )

    assert profile.multi_turn is False
    assert any("did not answer" in note for note in profile.notes)


def test_discovery_runs_against_the_real_runner():
    """The probes must survive the real execution path, not just a fake one."""
    profile = discover(_target())

    assert profile.id == "probe-target"
    assert profile.interface == "callable"
    # The stub answers "READY" to everything, so it fails the memory probe.
    assert profile.multi_turn is False
    assert profile.notes


def test_probe_categories_are_real_categories():
    assert PROBES[0].category is Category.endpoint_contract
    assert PROBES[1].category is Category.memory_context
