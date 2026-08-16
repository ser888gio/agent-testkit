"""Harness planning: profile + catalogs -> the plan a run executes.

This is the adaptive layer's decision point. Everything it decides is written
down, including what it decided against: an adapter that is not installed
becomes an exclusion with a reason, not a silently shorter run. "We did not test
this" is the finding a compliance reviewer needs most.

Control-plane only -- it ranks metadata and never calls an agent. Discovery
(`core/discovery.py`) is the part that touches one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from agentkit.core.adapters import ExternalEvalAdapter
from agentkit.core.catalog import build_catalog, rank
from agentkit.core.profile import (
    AgentProfile,
    ExcludedTest,
    HarnessPlan,
    SelectedTest,
    StopConditions,
)


def plan(
    profile: AgentProfile,
    tests: Iterable[Any],
    *,
    adapters: Sequence[ExternalEvalAdapter] = (),
    max_tests: int | None = None,
    attack_transforms: Sequence[str] = (),
    stop_on_critical: bool = False,
) -> HarnessPlan:
    entries = build_catalog(tests)
    unavailable: list[ExcludedTest] = []

    for adapter in adapters:
        adapter_entries = adapter.catalog(profile)
        if adapter.available():
            entries.extend(adapter_entries)
            continue
        unavailable.extend(
            ExcludedTest(
                test_id=entry.test_id,
                source=entry.source,
                reason=f"{adapter.name} is not installed on this runner",
            )
            for entry in adapter_entries
        )

    selected, excluded = rank(entries, profile, max_tests=max_tests)
    return HarnessPlan(
        profile=profile,
        selected=selected,
        excluded=[*excluded, *unavailable],
        sandbox=profile.sandbox,
        attack_transforms=list(attack_transforms),
        stop_conditions=StopConditions(max_tests=max_tests, stop_on_critical=stop_on_critical),
    )


def apply_plan(harness: HarnessPlan, tests: Iterable[Any]) -> tuple[list[Any], list[SelectedTest]]:
    """Split the plan into (runnable local tests, selections nothing here executes).

    Adapter-backed selections have no local test object: agentkit ranks them and
    generates the tool's invocation, but the tool itself is run out of band. The
    caller must surface the second list. A plan that claims a test was selected,
    next to a run with no evidence for it, reads as coverage that does not exist.
    """
    by_id = {test.id: test for test in tests}
    runnable = [by_id[choice.test_id] for choice in harness.selected if choice.test_id in by_id]
    unexecuted = [choice for choice in harness.selected if choice.test_id not in by_id]
    return runnable, unexecuted
