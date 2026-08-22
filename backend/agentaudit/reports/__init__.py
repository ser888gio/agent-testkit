"""Export a run + scores in formats CI and humans already understand."""

from __future__ import annotations

from agentaudit.core.profile import HarnessPlan
from agentaudit.core.schema import RunResult
from agentaudit.core.scoring import ScoreReport
from agentaudit.reports.compliance import to_compliance, to_compliance_json
from agentaudit.reports.coverage import to_coverage
from agentaudit.reports.html import to_html
from agentaudit.reports.json import to_json
from agentaudit.reports.junit import to_junit
from agentaudit.reports.md import to_markdown
from agentaudit.reports.plan import to_plan_markdown

# Renderers of a run's results. `plan` is not one of them -- a plan is not a
# result, and threading it through all seven would change a contract six modules
# depend on to serve one of them. It is dispatched separately below and listed
# alongside them, so callers pick a format string and never branch on which.
_RENDERERS = {
    "json": to_json,
    "junit": to_junit,
    "html": to_html,
    "md": to_markdown,
    "compliance": to_compliance,
    "compliance-json": to_compliance_json,
    "coverage": to_coverage,
}


FORMATS: tuple[str, ...] = (*_RENDERERS, "plan")


def render(
    run: RunResult,
    score: ScoreReport,
    fmt: str,
    *,
    plan: HarnessPlan | None = None,
) -> str:
    """Render one run in `fmt`. `plan` is read only by the `plan` format.

    Keyword-only with a default, so the six renderers that predate it are
    unaffected and no existing caller changes.
    """
    if fmt == "plan":
        return to_plan_markdown(plan)
    renderer = _RENDERERS.get(fmt)
    if renderer is None:
        valid = ", ".join(FORMATS)
        raise ValueError(f"unknown report format '{fmt}'; valid formats: {valid}")
    return renderer(run, score)


__all__ = [
    "FORMATS",
    "to_json",
    "to_junit",
    "to_html",
    "to_markdown",
    "to_plan_markdown",
    "to_compliance",
    "to_compliance_json",
    "to_coverage",
    "render",
]
