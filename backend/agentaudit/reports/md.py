"""Markdown report: score summary + failure bullet list, PR-comment friendly."""

from __future__ import annotations

from agentaudit.core.attacks import split_variant
from agentaudit.core.findings import detail_for, failures, provenance_for
from agentaudit.core.schema import RunResult
from agentaudit.core.scoring import ScoreReport
from agentaudit.core.timeline import build as build_timeline
from agentaudit.core.timeline import to_lines as timeline_lines
from agentaudit.core.timeline import window as window_timeline


def to_markdown(run: RunResult, score: ScoreReport) -> str:
    lines = [
        f"# agentaudit report - {run.agent_name}",
        "",
        "| Overall | Pass rate | Critical failures | Gate |",
        "|---|---|---|---|",
        f"| {score.overall_score * 100:.0f}% | {score.pass_rate * 100:.0f}% | "
        f"{score.critical_failures} | {'PASS' if score.gate_passed else 'BLOCK'} |",
        "",
        "## Failures",
        "",
    ]

    failing = failures(run.results)
    if not failing:
        lines.append("None.")
    else:
        lines.extend(_failure_lines(failing))

    return "\n".join(lines)


def _timeline_block(result) -> list[str]:
    """A failing multi-turn test's timeline, indented as a fenced code block."""
    timeline = window_timeline(build_timeline(result))
    if len(timeline["turns"]) < 2:
        return []
    lines = ["", "  Timeline (turn where the failure first appears is marked):", "", "  ```"]
    lines.extend(f"  {line}" for line in timeline_lines(timeline))
    lines.append("  ```")
    return lines


def _failure_lines(failing) -> list[str]:
    """One bullet per base test; attack variants roll up under it."""
    grouped: dict[str, list[tuple[str | None, str, object]]] = {}
    for r in failing:
        base, transform = split_variant(r.test_id)
        provenance = provenance_for(r)
        detail = f"{detail_for(r)} ({provenance})" if provenance else detail_for(r)
        grouped.setdefault(base, []).append((transform, detail, r))

    lines: list[str] = []
    for base, entries in grouped.items():
        variants = [(t, detail) for t, detail, _r in entries if t]
        if not variants:
            lines.append(f"- ❌ {base}: {entries[0][1]}")
            lines.extend(_timeline_block(entries[0][2]))
            continue
        lines.append(f"- ❌ {base} — {len(variants)} attack(s) bypassed")
        for transform, detail, r in entries:
            lines.append(f"  - {transform or 'original'}: {detail}")
            lines.extend(_timeline_block(r))
    return lines
