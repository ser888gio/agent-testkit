"""Markdown report: score summary + failure bullet list, PR-comment friendly."""

from __future__ import annotations

from agentaudit.core.attacks import split_variant
from agentaudit.core.findings import detail_for, failures, provenance_for
from agentaudit.core.schema import RunResult
from agentaudit.core.scoring import ScoreReport


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

    trial_lines = _trial_lines(run.results)
    if trial_lines:
        lines += ["", "## Trial policies", ""] + trial_lines

    return "\n".join(lines)


def _trial_lines(results) -> list[str]:
    """Per-test n / pass-rate / threshold, plus the extra agent-call cost,
    for every result that ran under `repeat:`/`trial:` (i.e. has `attempts`).
    """
    trialed = [r for r in results if r.attempts]
    if not trialed:
        return []
    lines = ["| Test | N | Pass rate | Threshold | Extra calls |", "|---|---|---|---|---|"]
    extra_calls = 0
    for r in trialed:
        n = len(r.attempts)
        rate = sum(1 for s in r.attempts if s.value == "passed") / n
        threshold = r.trial_threshold if r.trial_threshold is not None else 1.0
        extra_calls += n - 1
        lines.append(
            f"| {r.test_id} | {n} | {rate * 100:.0f}% | {threshold * 100:.0f}% | {n - 1} |"
        )
    lines.append("")
    lines.append(f"Total trial cost: +{extra_calls} agent call(s) beyond a single-run baseline.")
    return lines


def _failure_lines(failing) -> list[str]:
    """One bullet per base test; attack variants roll up under it."""
    grouped: dict[str, list[tuple[str | None, str]]] = {}
    for r in failing:
        base, transform = split_variant(r.test_id)
        provenance = provenance_for(r)
        detail = f"{detail_for(r)} ({provenance})" if provenance else detail_for(r)
        grouped.setdefault(base, []).append((transform, detail))

    lines: list[str] = []
    for base, entries in grouped.items():
        variants = [(t, detail) for t, detail in entries if t]
        if not variants:
            lines.append(f"- ❌ {base}: {entries[0][1]}")
            continue
        lines.append(f"- ❌ {base} — {len(variants)} attack(s) bypassed")
        lines.extend(f"  - {transform or 'original'}: {detail}" for transform, detail in entries)
    return lines
