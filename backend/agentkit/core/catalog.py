"""Test catalog: describe tests in selection terms, then rank them for one agent.

Selection is the point of the adaptive layer, so it has to be explainable.
Everything that survives ranking carries the reasons it did; everything dropped
carries the reason it did not. Both halves end up in the harness plan, because
"we did not test this" is evidence too.

Control-plane only: this module reasons about test metadata and never calls an
agent.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agentkit.core.assertions import REGISTRY as ASSERTION_REGISTRY
from agentkit.core.profile import AgentProfile, ExcludedTest, SelectedTest, TestCatalogEntry
from agentkit.core.schema import Category, Risk, TestCase

# Domains a pack tag can name. A tag outside this set is just a tag: it must not
# silently narrow a test to a domain nobody profiles as.
DOMAIN_TAGS = frozenset({"treasury", "email", "support", "retail", "finance", "scheduling"})

# Which capability an assertion needs to mean anything. Kept exhaustive against
# assertions.REGISTRY by tests/test_catalog.py -- an unclassified assertion would
# silently make its test look prerequisite-free and get selected for an agent
# that cannot exercise it.
_SANDBOX_ASSERTIONS = frozenset(
    {
        "no_payment_created",
        "payment_created",
        "payment_amount_max",
        "no_mail_sent_to",
        "mail_sent",
        "no_external_forward",
    }
)
_TOOL_ASSERTIONS = frozenset(
    {
        "tool_called",
        "tool_not_called",
        "tool_arg_equals",
        "tool_call_order",
        "no_repeated_tool",
    }
)

_RISK_BONUS = {Risk.low: 0.25, Risk.medium: 0.5, Risk.high: 1.0, Risk.critical: 2.0}

# Categories that only matter once an agent can actually do the thing.
_ACTION_CATEGORIES = frozenset({Category.action_safety, Category.tool_use})
_STATEFUL_CATEGORIES = frozenset({Category.memory_context})

# How much a second, third, ... test in an already-covered category is discounted.
# Breadth first: one probe per category before a fourth of the same kind.
_COVERAGE_DECAY = 0.3
_COST_WEIGHT = 0.15


def _requires(test: TestCase) -> list[str]:
    needs: set[str] = set()
    if test.turns or test.adaptive is not None:
        needs.add("multi_turn")
    if isinstance(test.input, dict) or any(isinstance(t, dict) for t in test.turns):
        needs.add("structured_input")
    for assertion in test.assertions:
        if assertion.name in _SANDBOX_ASSERTIONS:
            needs.add("sandbox")
        elif assertion.name in _TOOL_ASSERTIONS:
            needs.add("tool_use")
    if test.setup:
        needs.add("sandbox")
    return sorted(needs)


def _cost(test: TestCase) -> float:
    turns = test.adaptive.max_turns if test.adaptive is not None else max(len(test.turns), 1)
    return float(turns * test.repeat)


def entry_from_test(test: Any, source: str = "local") -> TestCatalogEntry:
    """Describe one discovered test in the catalog's vocabulary.

    Accepts both `TestCase` and the loader's `PythonTestCase`; the latter has no
    declarative body to inspect, so it is catalogued on its tags alone.
    """
    declarative = (
        {"requires": _requires(test), "cost": _cost(test)} if isinstance(test, TestCase) else {}
    )
    return TestCatalogEntry(
        test_id=test.id,
        source=source,
        category=test.category,
        risk=test.risk,
        domains=sorted(DOMAIN_TAGS.intersection(test.tags)),
        tags=list(test.tags),
        **declarative,
    )


def build_catalog(tests: Iterable[Any], source: str = "local") -> list[TestCatalogEntry]:
    return [entry_from_test(test, source) for test in tests]


def _relevance(entry: TestCatalogEntry, profile: AgentProfile) -> tuple[float, list[str]]:
    score = 1.0
    reasons = []

    if profile.domain in entry.domains:
        score += 1.5
        reasons.append(f"written for the {profile.domain} domain")
    elif not entry.domains:
        reasons.append("domain-agnostic")

    score += _RISK_BONUS[entry.risk]
    reasons.append(f"risk {entry.risk.value}")

    if profile.tool_use and entry.category in _ACTION_CATEGORIES:
        score += 1.0
        reasons.append("agent takes actions, so action safety is in scope")
    if profile.multi_turn and entry.category in _STATEFUL_CATEGORIES:
        score += 1.0
        reasons.append("agent carries context across turns")
    if entry.risk in (Risk.high, Risk.critical) and profile.risk_level in (
        Risk.high,
        Risk.critical,
    ):
        score += 0.5
        reasons.append(f"agent is profiled {profile.risk_level.value} risk")

    score -= _COST_WEIGHT * entry.cost
    return score, reasons


def rank(
    entries: Iterable[TestCatalogEntry],
    profile: AgentProfile,
    *,
    max_tests: int | None = None,
) -> tuple[list[SelectedTest], list[ExcludedTest]]:
    """Order the catalog for one agent. Returns (selected, excluded-with-reasons).

    Deterministic: ties break on test id, so the same profile and catalog always
    produce the same plan. Reproducibility is a compliance requirement, not a
    nicety.
    """
    capabilities = profile.capabilities()
    excluded: list[ExcludedTest] = []
    candidates: list[tuple[float, list[str], TestCatalogEntry]] = []

    for entry in sorted(entries, key=lambda e: e.test_id):
        missing = sorted(set(entry.requires) - capabilities)
        if missing:
            excluded.append(
                ExcludedTest(
                    test_id=entry.test_id,
                    source=entry.source,
                    reason=f"needs {', '.join(missing)}, which this agent does not expose",
                )
            )
            continue
        if entry.domains and profile.domain not in entry.domains:
            excluded.append(
                ExcludedTest(
                    test_id=entry.test_id,
                    source=entry.source,
                    reason=(
                        f"scoped to {', '.join(entry.domains)}; "
                        f"agent is profiled as {profile.domain}"
                    ),
                )
            )
            continue
        score, reasons = _relevance(entry, profile)
        candidates.append((score, reasons, entry))

    # Greedy: re-score against what is already covered and take the best each
    # round, so the emitted order is the order the planner actually believes.
    # ponytail: O(n^2) over the catalog. A heap pays off past a few thousand tests.
    selected: list[SelectedTest] = []
    seen_categories: dict[Category, int] = {}
    remaining = list(candidates)
    while remaining and (max_tests is None or len(selected) < max_tests):
        best = min(
            remaining,
            key=lambda c: (
                -(c[0] - _COVERAGE_DECAY * seen_categories.get(c[2].category, 0)),
                c[2].test_id,
            ),
        )
        remaining.remove(best)
        score, reasons, entry = best
        covered = seen_categories.get(entry.category, 0)
        if covered:
            reasons = [*reasons, f"{covered} test(s) already cover {entry.category.value}"]
        seen_categories[entry.category] = covered + 1
        selected.append(
            SelectedTest(
                test_id=entry.test_id,
                source=entry.source,
                score=round(score - _COVERAGE_DECAY * covered, 3),
                reasons=reasons,
            )
        )

    excluded.extend(
        ExcludedTest(
            test_id=entry.test_id,
            source=entry.source,
            reason=f"beyond the {max_tests}-test budget for this run",
        )
        for _, _, entry in sorted(remaining, key=lambda c: c[2].test_id)
    )

    return selected, excluded


def unclassified_assertions() -> set[str]:
    """Shipped assertions this module has no capability opinion about.

    Anything response-only lands here legitimately; the test asserts the set is
    exactly the response-only assertions, so a new sandbox or tool assertion has
    to be classified before it ships.

    Only assertions defined in `core/assertions.py` count. `REGISTRY` is a
    process-global that anything can decorate into at runtime, and a caller's
    own assertion is not this module's to classify.
    """
    shipped = {
        name
        for name, fn in ASSERTION_REGISTRY.items()
        if getattr(fn, "__module__", "") == "agentkit.core.assertions"
    }
    return shipped - _SANDBOX_ASSERTIONS - _TOOL_ASSERTIONS
