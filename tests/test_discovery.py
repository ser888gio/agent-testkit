from datetime import datetime, timezone

from agentaudit.core.config import CallableSpec, HTTPSpec, TargetConfig
from agentaudit.core.discovery import (
    ECHO_PROBE,
    MEMORY_PHRASE,
    MEMORY_PROBE,
    PROBES,
    TOOLS_PROBE,
    discover,
    parse_tool_names,
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


def _fake_runner(
    statuses: dict[str, Status],
    latency: float | None = 12.0,
    responses: dict[str, object] | None = None,
):
    now = datetime.now(timezone.utc)
    responses = responses or {}

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
                    status=statuses.get(t.id, Status.passed),
                    latency_ms=latency,
                    response=responses.get(t.id),
                    started_at=now,
                    finished_at=now,
                )
                for t in tests
            ],
        )

    return _run


def _discover_tools(reply, **kwargs):
    """Run discovery against an agent that answers the tools probe with `reply`."""
    return discover(
        _target(**kwargs),
        runner=_fake_runner(
            {ECHO_PROBE: Status.passed, MEMORY_PROBE: Status.failed},
            responses={TOOLS_PROBE: reply},
        ),
    )


def test_probes_are_cheap_and_bounded():
    assert [p.id for p in PROBES] == [ECHO_PROBE, MEMORY_PROBE, TOOLS_PROBE]
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


# An agent's own account of its tools is the cheapest read on its attack
# surface, but it is agent output, so parsing is deliberately unforgiving.
def test_self_reported_tools_land_in_the_profile():
    profile = _discover_tools("transfer_funds, list_invoices, send_email")
    assert profile.tool_classes == ["transfer_funds", "list_invoices", "send_email"]
    assert profile.tool_use is True
    assert any("named 3 tool(s)" in note for note in profile.notes)


def test_self_report_does_not_displace_what_the_sandbox_told_us():
    profile = _discover_tools("transfer_funds, banking", sandbox="treasury")
    # The sandbox's classes stay first and are not duplicated by a case variant.
    assert profile.tool_classes[:2] == ["banking", "invoicing"]
    assert "transfer_funds" in profile.tool_classes
    assert profile.tool_classes.count("banking") == 1


def test_an_agent_with_no_sandbox_that_names_tools_gets_tool_use():
    # This is the case the planner would otherwise skip every tool test for.
    assert profile_from_config(_target()).tool_use is False
    assert _discover_tools("read_file, run_query").tool_use is True


def test_none_is_recorded_as_no_tools():
    profile = _discover_tools("NONE")
    assert profile.tool_classes == []
    assert profile.tool_use is False
    assert any("did not name its tools" in note for note in profile.notes)


def test_a_prose_answer_is_discarded_rather_than_scraped():
    profile = _discover_tools(
        "I have access to several tools including a banking API and an email client."
    )
    assert profile.tool_classes == []
    assert profile.tool_use is False


def test_a_refusal_does_not_become_a_tool_name():
    profile = _discover_tools("I'm sorry, I can't share that information.")
    assert profile.tool_classes == []


def test_the_tool_list_is_capped():
    profile = _discover_tools(", ".join(f"tool_{i}" for i in range(80)))
    assert len(profile.tool_classes) == 24


def test_a_dropped_response_is_not_a_missing_tool_claim():
    # The evidence policy can decline to store a response; that is not the same
    # as the agent declining to answer.
    profile = _discover_tools(None)
    assert profile.tool_classes == []
    assert any("evidence policy" in note for note in profile.notes)


def test_tool_names_are_parsed_without_a_run():
    assert parse_tool_names("ab, cd") == ["ab", "cd"]
    # A single character is not a tool name; it is a stray token.
    assert parse_tool_names("a, b") == []
    assert parse_tool_names("`get_balance`, **send_mail**") == ["get_balance", "send_mail"]
    assert parse_tool_names("get_balance()") == ["get_balance"]
    # Duplicates collapse case-insensitively, keeping first-seen spelling.
    assert parse_tool_names("Send, send, SEND") == ["Send"]
    # Only the first line is read: a list followed by an explanation is a list.
    assert parse_tool_names("alpha, beta\nThese let me help you!") == ["alpha", "beta"]
    assert parse_tool_names("") == []
    assert parse_tool_names("none") == []
    # A name long enough to be prose is not a name.
    assert parse_tool_names("x" * 60) == []
