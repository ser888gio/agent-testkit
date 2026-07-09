"""Markdown report: score summary + failure bullet list, PR-comment friendly."""

from __future__ import annotations

from agentkit.core.schema import RunResult, Status
from agentkit.core.scoring import ScoreReport


def _detail_for(r) -> str:
    for a in r.assertion_results:
        if not a.passed:
            return a.detail
    return r.error or ""


def to_markdown(run: RunResult, score: ScoreReport) -> str:
    lines = [
        f"# agentkit report - {run.agent_name}",
        "",
        "| Overall | Pass rate | Critical failures | Gate |",
        "|---|---|---|---|",
        f"| {score.overall_score * 100:.0f}% | {score.pass_rate * 100:.0f}% | "
        f"{score.critical_failures} | {'PASS' if score.gate_passed else 'BLOCK'} |",
        "",
        "## Failures",
        "",
    ]

    failing = sorted(
        (r for r in run.results if r.status in (Status.failed, Status.error)),
        key=lambda r: r.test_id,
    )
    if not failing:
        lines.append("None.")
    else:
        for r in failing:
            lines.append(f"- ❌ {r.test_id}: {_detail_for(r)}")

    return "\n".join(lines)
