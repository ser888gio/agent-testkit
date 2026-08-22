"""Coverage report: which (category, attack style) cells a run actually probed.

The other reports answer "what failed". This one answers "what did you not
test", which is the question a reviewer cannot reconstruct from results — an
absent finding and an absent test look identical in a pass/fail list.

It also separates reviewed evidence from machine-authored evidence. A generated
test is real evidence, but it has not been through a human, so a report that
folded both into one number would let an unreviewed test move a compliance
figure on its own. They are counted apart and labelled.

Control-plane: derives from an already-redacted `RunResult`.
"""

from __future__ import annotations

from agentaudit.core.archive import STYLES
from agentaudit.core.attacks import split_variant
from agentaudit.core.evolve import GENERATED_PREFIX, PROMOTED_PREFIX
from agentaudit.core.schema import Category, RunResult, Status
from agentaudit.core.scoring import ScoreReport


def _style_of_result(test_id: str) -> str:
    """The attack style a result exercised, from its id alone.

    `archive.style_of` needs a `TestCase`; a report only has results, and the
    id carries the transform. An adaptive ladder is not recoverable this way,
    so it reads as the base style — stated here rather than silently wrong.
    """
    _, transform = split_variant(test_id)
    return transform if transform in STYLES else "plain"


def _origin(test_id: str) -> str:
    head = test_id.split(".", 1)[0]
    if head == GENERATED_PREFIX:
        return "generated"
    if head == PROMOTED_PREFIX:
        return "promoted"
    return "authored"


def to_coverage(run: RunResult, score: ScoreReport) -> str:  # noqa: ARG001
    """`score` is unused: every renderer takes (run, score) so `render` can
    dispatch on format alone. Coverage is derived entirely from results.
    """
    probed: dict[tuple[Category, str], list[Status]] = {}
    origins: dict[str, int] = {"authored": 0, "promoted": 0, "generated": 0}

    for result in run.results:
        if result.status is Status.skipped:
            continue
        cell = (result.category, _style_of_result(result.test_id))
        probed.setdefault(cell, []).append(result.status)
        origins[_origin(result.test_id)] += 1

    categories = sorted({c for c, _ in probed}, key=lambda c: c.value)
    lines = [
        f"# agentaudit coverage - {run.agent_name}",
        "",
        f"Probed {len(probed)} cell(s) across {len(categories)} categor(ies).",
        "",
        "## Evidence by origin",
        "",
        "| Origin | Results | Reviewed |",
        "|---|---|---|",
        f"| Hand-authored | {origins['authored']} | yes |",
        f"| Promoted | {origins['promoted']} | yes, by a human |",
        f"| Generated | {origins['generated']} | **no - provisional** |",
    ]
    if origins["generated"]:
        lines += [
            "",
            "> Generated results come from machine-authored tests that no human has "
            "reviewed. They are reported as evidence but must not be read as a "
            "reviewed control.",
        ]

    lines += [
        "",
        "## Probed cells",
        "",
        "| Category | Style | Results | Failed |",
        "|---|---|---|---|",
    ]
    for cell in sorted(probed, key=lambda c: (c[0].value, c[1])):
        statuses = probed[cell]
        failed = sum(1 for s in statuses if s in (Status.failed, Status.error))
        lines.append(f"| {cell[0].value} | {cell[1]} | {len(statuses)} | {failed} |")

    # The honest half. Restricted to categories this run actually touched: the
    # full 9x25 product would report an agent as uncovered for categories
    # nobody intended to probe, which is noise, not a finding.
    missing = sorted(
        (
            (category, style)
            for category in categories
            for style in STYLES
            if (category, style) not in probed
        ),
        key=lambda c: (c[0].value, c[1]),
    )
    lines += ["", f"## Not probed ({len(missing)})", ""]
    if not missing:
        lines.append("Every style was probed in every category this run touched.")
    else:
        by_category: dict[str, list[str]] = {}
        for category, style in missing:
            by_category.setdefault(category.value, []).append(style)
        lines.extend(
            f"- **{category}**: {', '.join(styles)}" for category, styles in by_category.items()
        )
        lines += [
            "",
            "> An unprobed cell is not a pass. It is ground this run did not cover.",
        ]

    return "\n".join(lines)


__all__ = ["to_coverage"]
