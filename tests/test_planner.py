from agentkit.core.adapters import ExternalEvalAdapter
from agentkit.core.planner import apply_plan, plan
from agentkit.core.profile import AgentProfile, TestCatalogEntry
from agentkit.core.schema import Assertion, Category, Risk
from agentkit.core.schema import TestCase as SchemaTestCase


class _StubAdapter(ExternalEvalAdapter):
    def __init__(self, name, installed):
        self.name = name
        self._installed = installed

    def available(self):
        return self._installed

    def catalog(self, profile):
        return [
            TestCatalogEntry(
                test_id=f"{self.name}.probe",
                source=self.name,
                category=Category.prompt_injection,
                risk=Risk.high,
                cost=5.0,
            )
        ]

    def normalize(self, raw, *, evidence=None, started_at=None):
        return []


def _test_case(test_id, **kwargs):
    kwargs.setdefault("category", Category.prompt_injection)
    kwargs.setdefault("assertions", [Assertion(name="response_nonempty")])
    kwargs.setdefault("input", "hello")
    return SchemaTestCase(id=test_id, **kwargs)


def test_plan_records_the_profile_sandbox_and_stop_conditions():
    profile = AgentProfile(id="t", domain="treasury", sandbox="treasury", tool_use=True)

    harness = plan(
        profile,
        [_test_case("a.b.one")],
        max_tests=5,
        attack_transforms=["base64"],
        stop_on_critical=True,
    )

    assert harness.profile == profile
    assert harness.sandbox == "treasury"
    assert harness.attack_transforms == ["base64"]
    assert harness.stop_conditions.max_tests == 5
    assert harness.stop_conditions.stop_on_critical is True


def test_an_uninstalled_adapter_becomes_an_exclusion_not_a_shorter_run():
    harness = plan(
        AgentProfile(id="t"),
        [_test_case("a.b.one")],
        adapters=[_StubAdapter("promptfoo", installed=False)],
    )

    assert harness.selected_ids() == ["a.b.one"]
    missing = [e for e in harness.excluded if e.source == "promptfoo"]
    assert missing and "not installed" in missing[0].reason


def test_an_installed_adapter_competes_with_local_tests():
    harness = plan(
        AgentProfile(id="t"),
        [_test_case("a.b.one", risk=Risk.low)],
        adapters=[_StubAdapter("garak", installed=True)],
    )

    assert set(harness.selected_ids()) == {"a.b.one", "garak.probe"}
    sources = {s.test_id: s.source for s in harness.selected}
    assert sources["garak.probe"] == "garak"


def test_apply_plan_separates_runnable_tests_from_external_selections():
    tests = [_test_case("a.b.low", risk=Risk.low), _test_case("a.b.crit", risk=Risk.critical)]
    harness = plan(
        AgentProfile(id="t"), tests, adapters=[_StubAdapter("garak", installed=True)]
    )

    ordered, unexecuted = apply_plan(harness, tests)

    assert [t.id for t in ordered] == [
        test_id for test_id in harness.selected_ids() if test_id.startswith("a.b.")
    ]
    assert ordered[0].id == "a.b.crit"
    # An adapter selection is reported, never silently dropped: a plan claiming
    # coverage next to a run with no evidence for it is worse than no plan.
    assert [u.test_id for u in unexecuted] == ["garak.probe"]


def test_planning_is_reproducible_for_the_same_profile_and_catalog():
    profile = AgentProfile(id="t", domain="treasury", tool_use=True, multi_turn=True)
    tests = [_test_case(f"a.b.case{i}") for i in range(8)]

    first = plan(profile, tests, max_tests=4)
    second = plan(profile, tests, max_tests=4)

    assert first.selected == second.selected
    assert first.excluded == second.excluded
