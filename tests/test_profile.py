from agentaudit.core.profile import (
    AgentProfile,
    ExcludedTest,
    HarnessPlan,
    SelectedTest,
    StopConditions,
)
from agentaudit.core.profile import TestCatalogEntry as CatalogEntry
from agentaudit.core.schema import Category, Risk


def test_profile_capabilities_reflect_what_the_agent_supports():
    bare = AgentProfile(id="bare")
    assert bare.capabilities() == set()

    rich = AgentProfile(
        id="rich", multi_turn=True, tool_use=True, sandbox="treasury", structured_input=True
    )
    assert rich.capabilities() == {"multi_turn", "tool_use", "sandbox", "structured_input"}


def test_catalog_entry_defaults_are_domain_agnostic():
    entry = CatalogEntry(test_id="core.a.b", category=Category.prompt_injection)
    assert entry.source == "local"
    assert entry.domains == []
    assert entry.requires == []
    assert entry.risk is Risk.medium


def test_harness_plan_round_trips_through_json():
    plan = HarnessPlan(
        profile=AgentProfile(
            id="treasury-agent",
            domain="treasury",
            sandbox="treasury",
            tool_use=True,
            risk_level=Risk.high,
            policy_tags=["eu_ai_act.art15"],
        ),
        selected=[
            SelectedTest(
                test_id="core.prompt_injection.instruction_override",
                source="local",
                score=3.5,
                reasons=["domain match: treasury", "high-risk surface"],
            )
        ],
        excluded=[
            ExcludedTest(test_id="core.memory.carryover", source="local", reason="needs multi_turn")
        ],
        sandbox="treasury",
        attack_transforms=["base64"],
        stop_conditions=StopConditions(max_tests=10, stop_on_critical=True),
    )

    restored = HarnessPlan.model_validate_json(plan.model_dump_json())

    assert restored == plan
    assert restored.selected_ids() == ["core.prompt_injection.instruction_override"]
    assert restored.excluded[0].reason == "needs multi_turn"
