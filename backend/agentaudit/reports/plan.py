"""Harness plan report: what was selected, why, and what was left untested.

A plan is not a result, so it is not one of the `_RENDERERS` that take
`(run, score)` -- threading an optional plan through all of them would change a
contract six modules depend on to serve one of them. `reports.render` dispatches
`plan` separately and lists it in `FORMATS`, so callers still pick a format
string and never branch on which one they picked.
"""

from __future__ import annotations

from agentaudit.core.profile import HarnessPlan

NO_PLAN = (
    "This run was launched without a planner, so there is no selection rationale "
    "to report. Use `agentaudit run --plan` to record one."
)


def to_plan_markdown(plan: HarnessPlan | None) -> str:
    if plan is None:
        return NO_PLAN

    profile = plan.profile
    lines = [
        f"# agentaudit plan - {profile.id}",
        "",
        "## Discovered profile",
        "",
        f"- Domain: {profile.domain}",
        f"- Interface: {profile.interface}",
        f"- Risk level: {profile.risk_level.value}",
        f"- Multi-turn: {'yes' if profile.multi_turn else 'no'}",
        f"- Tool use: {'yes' if profile.tool_use else 'no'}",
        f"- Sandbox: {profile.sandbox or 'none'}",
    ]
    if profile.side_effects:
        lines.append(f"- Side effects: {', '.join(profile.side_effects)}")
    lines.extend(f"- {note}" for note in profile.notes)

    lines += ["", f"## Selected tests ({len(plan.selected)})", ""]
    if not plan.selected:
        lines.append("None.")
    else:
        lines.append("| Score | Test | Source | Why |")
        lines.append("|---|---|---|---|")
        lines.extend(
            f"| {choice.score:.2f} | `{choice.test_id}` | {choice.source} | "
            f"{'; '.join(choice.reasons)} |"
            for choice in plan.selected
        )

    external = [choice for choice in plan.selected if choice.source != "local"]
    if external:
        lines += [
            "",
            f"> {len(external)} selection(s) above are executed by an external tool, not by "
            f"this agentaudit run, so this run holds no evidence for them: "
            f"{', '.join(choice.test_id for choice in external)}.",
        ]

    # The untested half is the part a reviewer cannot reconstruct from results.
    lines += ["", f"## Not tested ({len(plan.excluded)})", ""]
    if not plan.excluded:
        lines.append("Nothing was excluded.")
    else:
        lines.extend(f"- `{item.test_id}` ({item.source}): {item.reason}" for item in plan.excluded)

    if plan.attack_transforms:
        lines += ["", f"Attack transforms applied: {', '.join(plan.attack_transforms)}."]

    return "\n".join(lines)
