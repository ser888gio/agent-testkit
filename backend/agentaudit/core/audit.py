"""One assembly of an audit run: discover -> plan -> attack -> run -> score.

Both entry points that grade an agent -- `cli.run_cmd` and `worker.execute_job`
-- used to spell this sequence out themselves, and the copies had already
drifted: only one of them bound discovery to the egress decision the run was
going to use. The order lives here now, and the differences between the two
callers (who resolved the egress decision, whether a credential is in the
redactor, whether to plan, which attack transforms, how to report progress) are
parameters rather than a second body of code.

Control-plane callers keep only their own concerns: flags and tables in the CLI,
job rows and leases in the worker.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from agentaudit.core.adapters import ADAPTERS
from agentaudit.core.attacks import expand
from agentaudit.core.config import HTTPSpec, TargetConfig
from agentaudit.core.discovery import discover
from agentaudit.core.egress import ValidatedEndpoint
from agentaudit.core.planner import apply_plan
from agentaudit.core.planner import plan as plan_harness
from agentaudit.core.profile import HarnessPlan, SelectedTest
from agentaudit.core.redaction import Redactor
from agentaudit.core.runner import run as run_tests
from agentaudit.core.schema import RunResult, TestResult
from agentaudit.core.scoring import ScoreReport, score


@dataclass(frozen=True)
class AuditRun:
    """Everything one assembled run produced, redacted and ready to persist."""

    result: RunResult
    report: ScoreReport
    plan: HarnessPlan | None = None
    unexecuted: list[SelectedTest] = field(default_factory=list)


def run_external(
    target: TargetConfig,
    harness: HarnessPlan,
    unexecuted: list[SelectedTest],
) -> tuple[list[TestResult], list[SelectedTest]]:
    """Run the third-party tools the plan selected. Returns (results, still unexecuted).

    A selection is executed through the same seam it was selected through, so a
    plan that claims a test was chosen is backed by evidence for it. What no
    adapter here can run stays in the second list, for the caller to surface.
    """
    if not isinstance(target.agent, HTTPSpec):
        # A callable target has no URL to hand a scanner that dials for itself.
        return [], unexecuted

    by_source: dict[str, list[SelectedTest]] = {}
    for choice in unexecuted:
        by_source.setdefault(choice.source, []).append(choice)

    results: list[TestResult] = []
    remaining: list[SelectedTest] = []
    for source, choices in sorted(by_source.items()):
        adapter = ADAPTERS.get(source)
        if adapter is None:
            remaining.extend(choices)
            continue
        results.extend(
            adapter.execute(
                harness.profile,
                target.agent.endpoint,
                selected=[choice.test_id for choice in choices],
                evidence=target.evidence,
            )
        )
    return results, remaining


def execute(
    target: TargetConfig,
    tests: list[Any],
    *,
    redactor: Redactor | None = None,
    endpoint: ValidatedEndpoint | None = None,
    plan: bool = False,
    max_tests: int | None = None,
    attack_transforms: Sequence[str] = (),
    external: bool = False,
    fail_under: float = 0.0,
    block_on_critical: bool = True,
    on_plan: Callable[[list[Any], HarnessPlan | None, list[SelectedTest]], None] | None = None,
    on_test: Callable[[int, Any], None] | None = None,
) -> AuditRun:
    """Assemble and grade one run.

    `endpoint` carries an egress decision the caller already made -- validation
    needs the target's allowlist, which is a Store concern neither this module
    nor the runner may reach into. Whatever is passed binds *every* request the
    run makes, discovery probes included, so probing cannot reach an endpoint
    the run's own policy would reject.

    `on_plan` fires once with the tests that are about to run, so a caller can
    print or log the plan before evidence starts arriving.

    `external` spawns the third-party tools the plan selected. Off by default,
    and a hosted caller must leave it off: a spawned tool re-resolves the
    hostname itself, so `endpoint`'s pinned address does not bind it. See
    `ExternalEvalAdapter`.
    """
    transforms = [name for name in attack_transforms if name]

    def bound_run(cfg: TargetConfig, cases: list[Any]) -> RunResult:
        return run_tests(cfg, cases, redactor=redactor, endpoint=endpoint)

    harness: HarnessPlan | None = None
    unexecuted: list[SelectedTest] = []
    if plan:
        harness = plan_harness(
            discover(target, runner=bound_run),
            tests,
            adapters=list(ADAPTERS.values()),
            max_tests=max_tests,
            attack_transforms=transforms,
        )
        tests, unexecuted = apply_plan(harness, tests)

    if transforms:
        tests = expand(tests, transforms)

    if on_plan is not None:
        on_plan(tests, harness, unexecuted)

    result = run_tests(target, tests, redactor=redactor, endpoint=endpoint, on_test=on_test)

    if external and harness is not None and unexecuted:
        external_results, unexecuted = run_external(target, harness, unexecuted)
        if external_results:
            result = result.model_copy(
                update={"results": [*result.results, *external_results]}
            )

    return AuditRun(
        result=result,
        report=score(result, fail_under=fail_under, block_on_critical=block_on_critical),
        plan=harness,
        unexecuted=unexecuted,
    )
