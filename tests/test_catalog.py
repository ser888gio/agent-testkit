import pytest

from agentkit.core.assertions import REGISTRY
from agentkit.core.catalog import build_catalog, entry_from_test, rank, unclassified_assertions
from agentkit.core.profile import AgentProfile
from agentkit.core.schema import Assertion, Category, Risk
from agentkit.core.schema import TestCase as SchemaTestCase

# Assertions that read the response alone: no sandbox, no tool ledger.
RESPONSE_ONLY = {
    "contains_any",
    "not_contains",
    "matches_regex",
    "response_nonempty",
    "is_valid_json",
    "status_ok",
    "latency_under",
    "mentions_approval_required",
}


def _test_case(test_id, **kwargs):
    kwargs.setdefault("category", Category.prompt_injection)
    kwargs.setdefault("assertions", [Assertion(name="response_nonempty")])
    if "turns" not in kwargs:
        kwargs.setdefault("input", "hello")
    return SchemaTestCase(id=test_id, **kwargs)


def test_every_registered_assertion_is_classified():
    """A new sandbox/tool assertion must declare its capability, or tests mis-select."""
    assert unclassified_assertions() == RESPONSE_ONLY
    assert RESPONSE_ONLY <= set(REGISTRY)


def test_entry_infers_prerequisites_from_the_test_body():
    plain = entry_from_test(_test_case("a.plain.case"))
    assert plain.requires == []
    assert plain.cost == pytest.approx(1.0)

    multi = entry_from_test(_test_case("a.multi.case", turns=["one", "two", "three"]))
    assert multi.requires == ["multi_turn"]
    assert multi.cost == pytest.approx(3.0)

    sandboxed = entry_from_test(
        _test_case(
            "a.sandbox.case",
            category=Category.action_safety,
            assertions=[Assertion(name="no_payment_created")],
        )
    )
    assert sandboxed.requires == ["sandbox"]

    tooled = entry_from_test(
        _test_case(
            "a.tool.case",
            category=Category.tool_use,
            assertions=[Assertion(name="tool_called", args={"name": "send"})],
        )
    )
    assert tooled.requires == ["tool_use"]


def test_entry_reads_the_domain_off_pack_tags():
    entry = entry_from_test(_test_case("a.b.c", tags=["treasury", "action_safety"]))
    assert entry.domains == ["treasury"]
    # action_safety is a category tag, not a domain, and must not narrow the test.
    assert entry_from_test(_test_case("a.b.d", tags=["core", "action_safety"])).domains == []


def test_repeat_and_adaptive_raise_the_cost():
    assert entry_from_test(_test_case("a.b.c", repeat=3)).cost == pytest.approx(3.0)
    adaptive = _test_case("a.b.d", adaptive={"strategy": "crescendo", "max_turns": 5})
    assert entry_from_test(adaptive).cost == pytest.approx(5.0)


def test_tests_the_agent_cannot_satisfy_are_excluded_with_a_reason():
    catalog = build_catalog(
        [
            _test_case("a.plain.case"),
            _test_case("a.multi.case", turns=["one", "two"]),
            _test_case(
                "a.sandbox.case",
                category=Category.action_safety,
                assertions=[Assertion(name="payment_created")],
            ),
        ]
    )
    stateless = AgentProfile(id="chatbot", domain="generic")

    selected, excluded = rank(catalog, stateless)

    assert [s.test_id for s in selected] == ["a.plain.case"]
    reasons = {e.test_id: e.reason for e in excluded}
    assert "multi_turn" in reasons["a.multi.case"]
    assert "sandbox" in reasons["a.sandbox.case"]


def test_other_domains_tests_are_not_selected():
    catalog = build_catalog(
        [
            _test_case("t.pay.case", tags=["treasury"]),
            _test_case("e.mail.case", tags=["email"]),
            _test_case("c.any.case", tags=["core"]),
        ]
    )

    selected, excluded = rank(catalog, AgentProfile(id="a", domain="treasury"))

    assert [s.test_id for s in selected] == ["t.pay.case", "c.any.case"]
    assert [e.test_id for e in excluded] == ["e.mail.case"]
    assert "profiled as treasury" in excluded[0].reason


def test_domain_and_risk_drive_the_ordering_and_the_explanation():
    catalog = build_catalog(
        [
            _test_case("c.low.case", risk=Risk.low, tags=["core"]),
            _test_case("t.crit.case", risk=Risk.critical, tags=["treasury"]),
        ]
    )

    selected, _ = rank(catalog, AgentProfile(id="a", domain="treasury"))

    assert [s.test_id for s in selected] == ["t.crit.case", "c.low.case"]
    assert "written for the treasury domain" in selected[0].reasons
    assert "risk critical" in selected[0].reasons


def test_breadth_first_coverage_discounts_a_repeated_category():
    catalog = build_catalog(
        [
            _test_case("a.inj.one", category=Category.prompt_injection, risk=Risk.high),
            _test_case("a.inj.two", category=Category.prompt_injection, risk=Risk.high),
            _test_case("a.leak.one", category=Category.data_leakage, risk=Risk.high),
        ]
    )

    selected, _ = rank(catalog, AgentProfile(id="a"))

    scores = {s.test_id: s.score for s in selected}
    assert scores["a.inj.one"] > scores["a.inj.two"]
    assert scores["a.leak.one"] == scores["a.inj.one"]
    assert any("already cover prompt_injection" in r for r in selected[-1].reasons)


def test_budget_excludes_the_tail_rather_than_truncating_silently():
    catalog = build_catalog(
        [_test_case(f"a.b.case{i}", risk=Risk.low) for i in range(5)]
    )

    selected, excluded = rank(catalog, AgentProfile(id="a"), max_tests=2)

    assert len(selected) == 2
    assert len(excluded) == 3
    assert all("2-test budget" in e.reason for e in excluded)


def test_ranking_is_deterministic():
    catalog = build_catalog([_test_case(f"a.b.case{i}") for i in range(6)])
    profile = AgentProfile(id="a", domain="treasury", multi_turn=True)

    first = rank(catalog, profile)
    second = rank(list(reversed(catalog)), profile)

    assert first == second
