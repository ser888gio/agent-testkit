"""Endpoint discovery: probe a live agent, infer the profile the planner ranks against.

Runner-side. Discovery reaches a real endpoint, so it goes through `runner.run`
rather than calling `build_agent` directly -- that buys process isolation, the
egress decision, timeouts and redaction without a second execution path that
would have to be audited separately.

What lands in the profile is deliberately narrow: booleans, names and counts.
Agent output is never copied into an `AgentProfile`, because a profile is
persisted inside the harness plan and would sidestep the evidence policy.
"""

from __future__ import annotations

from collections.abc import Callable

from agentkit.core.config import HTTPSpec, TargetConfig
from agentkit.core.profile import AgentProfile
from agentkit.core.runner import run as run_tests
from agentkit.core.schema import Assertion, Category, Risk, RunResult, Status, TestCase

# A distinctive phrase an agent has no reason to emit unless it was remembered.
# Not a credential -- naming it *_TOKEN trips secret scanners on a literal that
# is deliberately public probe content.
MEMORY_PHRASE = "ORANGE-7391"

ECHO_PROBE = "discovery.probe.echo"
MEMORY_PROBE = "discovery.probe.memory"

# What each built-in sandbox says about the agent wired to it. The sandbox *is*
# the tool surface in this runtime, so it is the strongest signal available
# without asking the customer to fill in a questionnaire.
SANDBOX_SURFACES: dict[str, dict] = {
    "treasury": {
        "domain": "treasury",
        "purpose": "reviews and pays supplier invoices",
        "tool_classes": ["banking", "invoicing"],
        "side_effects": ["money_movement"],
        "risk_level": Risk.critical,
    },
    "email": {
        "domain": "email",
        "purpose": "reads and sends mail on the user's behalf",
        "tool_classes": ["mailbox", "contacts"],
        "side_effects": ["outbound_email", "data_disclosure"],
        "risk_level": Risk.high,
    },
}

PROBES: list[TestCase] = [
    TestCase(
        id=ECHO_PROBE,
        category=Category.endpoint_contract,
        risk=Risk.low,
        input="Reply with the single word READY.",
        assertions=[Assertion(name="response_nonempty")],
        tags=["discovery"],
        timeout_s=15.0,
    ),
    TestCase(
        id=MEMORY_PROBE,
        category=Category.memory_context,
        risk=Risk.low,
        turns=[
            f"Remember this reference code for later: {MEMORY_PHRASE}.",
            "What reference code did I ask you to remember?",
        ],
        assertions=[Assertion(name="contains_any", args={"values": [MEMORY_PHRASE]})],
        tags=["discovery"],
        timeout_s=15.0,
    ),
]


def profile_from_config(config: TargetConfig) -> AgentProfile:
    """The half of the profile that needs no traffic. Safe to call offline."""
    surface = SANDBOX_SURFACES.get(config.sandbox or "", {})
    http = config.agent if isinstance(config.agent, HTTPSpec) else None
    return AgentProfile(
        id=config.id,
        purpose=surface.get("purpose", ""),
        domain=surface.get("domain", "generic"),
        interface=config.agent.type,
        sandbox=config.sandbox,
        # A sandbox is a set of callable side effects: that is what tool_use means.
        tool_use=config.sandbox is not None,
        structured_input=bool(http.request) if http else False,
        tool_classes=list(surface.get("tool_classes", [])),
        side_effects=list(surface.get("side_effects", [])),
        risk_level=surface.get("risk_level", Risk.medium),
        notes=[
            f"{config.agent.type} interface",
            f"sandbox: {config.sandbox}" if config.sandbox else "no sandbox declared",
        ],
    )


def discover(
    config: TargetConfig,
    *,
    runner: Callable[[TargetConfig, list[TestCase]], RunResult] = run_tests,
) -> AgentProfile:
    """Probe the endpoint and return the profile the planner ranks against.

    `runner` is injectable so a caller that already made the egress decision can
    pass the same bound execution path the run will use.
    """
    profile = profile_from_config(config)
    result = runner(config, list(PROBES))
    by_id = {r.test_id: r for r in result.results}

    echo = by_id.get(ECHO_PROBE)
    if echo is None or echo.status is not Status.passed:
        detail = echo.error if echo is not None and echo.error else "no usable response"
        profile.notes.append(f"endpoint did not answer a trivial probe ({detail})")
        return profile

    latency = f"{echo.latency_ms:.0f} ms" if echo.latency_ms is not None else "unmeasured"
    profile.notes.append(f"answered a trivial probe in {latency}")

    memory = by_id.get(MEMORY_PROBE)
    profile.multi_turn = memory is not None and memory.status is Status.passed
    profile.notes.append(
        "carried a value across two turns"
        if profile.multi_turn
        else "did not carry a value across two turns: treated as stateless"
    )
    return profile
