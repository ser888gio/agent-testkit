"""Export a run + scores in formats CI and humans already understand."""

from __future__ import annotations

from agentaudit.core.schema import RunResult
from agentaudit.core.scoring import ScoreReport
from agentaudit.reports.compliance import to_compliance, to_compliance_json
from agentaudit.reports.html import to_html
from agentaudit.reports.json import to_json
from agentaudit.reports.junit import to_junit
from agentaudit.reports.md import to_markdown
from agentaudit.reports.plan import to_plan_markdown

_RENDERERS = {
    "json": to_json,
    "junit": to_junit,
    "html": to_html,
    "md": to_markdown,
    "compliance": to_compliance,
    "compliance-json": to_compliance_json,
}


def render(run: RunResult, score: ScoreReport, fmt: str) -> str:
    renderer = _RENDERERS.get(fmt)
    if renderer is None:
        valid = ", ".join(_RENDERERS)
        raise ValueError(f"unknown report format '{fmt}'; valid formats: {valid}")
    return renderer(run, score)


__all__ = [
    "to_json",
    "to_junit",
    "to_html",
    "to_markdown",
    "to_plan_markdown",
    "to_compliance",
    "to_compliance_json",
    "render",
]
