"""Export a run + scores in formats CI and humans already understand."""

from __future__ import annotations

from agentkit.core.schema import RunResult
from agentkit.core.scoring import ScoreReport
from agentkit.reports.html import to_html
from agentkit.reports.json import to_json
from agentkit.reports.junit import to_junit
from agentkit.reports.md import to_markdown

_RENDERERS = {
    "json": to_json,
    "junit": to_junit,
    "html": to_html,
    "md": to_markdown,
}


def render(run: RunResult, score: ScoreReport, fmt: str) -> str:
    renderer = _RENDERERS.get(fmt)
    if renderer is None:
        valid = ", ".join(_RENDERERS)
        raise ValueError(f"unknown report format '{fmt}'; valid formats: {valid}")
    return renderer(run, score)


__all__ = ["to_json", "to_junit", "to_html", "to_markdown", "render"]
