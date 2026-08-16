"""Markdown report: score summary + failure bullet list, PR-comment friendly."""

from __future__ import annotations

from agentkit.core.attacks import split_variant
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
        lines.extend(_failure_lines(failing))

    return "\n".join(lines)


def _failure_lines(failing) -> list[str]:
    """One bullet per base test; attack variants roll up under it."""
    grouped: dict[str, list[tuple[str | None, str]]] = {}
    for r in failing:
        base, transform = split_variant(r.test_id)
        grouped.setdefault(base, []).append((transform, _detail_for(r)))

    lines: list[str] = []
    for base, entries in grouped.items():
        variants = [(t, detail) for t, detail in entries if t]
        if not variants:
            lines.append(f"- ❌ {base}: {entries[0][1]}")
            continue
        lines.append(f"- ❌ {base} — {len(variants)} attack(s) bypassed")
        lines.extend(f"  - {transform or 'original'}: {detail}" for transform, detail in entries)
    return lines
