"""Compliance report: reframe pass/fail results as EU AI Act / OWASP evidence.

Same (run, score) -> str interface as reports/md.py. Evidence is already redacted
upstream, so there is no new redaction path here. See docs/archive/plans/MERGED-PLAN.md §0e.
"""

from __future__ import annotations

import json

from agentkit.core.attacks import split_variant
from agentkit.core.compliance import UNCOVERED, controls_for
from agentkit.core.schema import RunResult, Status
from agentkit.core.scoring import ScoreReport
from agentkit.reports.md import _detail_for

_DISCLAIMER = (
    "agentkit produces **technical readiness evidence for the risk-management file, "
    "not a compliance / CE / conformity determination**. The legal conclusion stays "
    "with the provider, deployer, or qualified assessor. Reg. (EU) 2024/1689 is the "
    "binding baseline; pending instruments (e.g. the Digital Omnibus) are not merged "
    "into it here."
)


def _rollup(results):
    """Group results by EU AI Act article -> {covered, gaps, not_tested, iso, nist}."""
    by_article: dict[str, dict] = {}
    for r in results:
        ctrl = controls_for(r)
        for article in ctrl.eu_ai_act:
            slot = by_article.setdefault(
                article,
                {"covered": 0, "gaps": [], "not_tested": 0, "iso": set(), "nist": set()},
            )
            slot["iso"].add(ctrl.iso_42001)
            slot["nist"].add(ctrl.nist_ai_rmf)
            if r.status == Status.passed:
                slot["covered"] += 1
            elif r.status in (Status.failed, Status.error):
                # Base id, deduplicated: N encodings of one bypass are one control
                # gap, not N. Which encoding got through stays in the failure narrative.
                base, _ = split_variant(r.test_id)
                if base not in slot["gaps"]:
                    slot["gaps"].append(base)
            else:
                slot["not_tested"] += 1
    return by_article


def _critical_fail_lines(critical_fail: list) -> list[str]:
    if not critical_fail:
        return []
    lines = [
        "Critical failures are evidence for the Art. 9 risk-management file "
        "(and Art. 55 model-eval where a GPAI provider):",
        "",
    ]
    for r in critical_fail:
        lines.append(f"- FAIL {r.test_id}: {_detail_for(r)}")
    lines.append("")
    return lines


def _article_rollup_lines(results) -> list[str]:
    rollup = _rollup(results)
    lines = [
        "## By EU AI Act article",
        "",
        "| Article | Covered | Gaps | Not tested | ISO 42001 | NIST |",
        "|---|---|---|---|---|---|",
    ]
    for article in sorted(rollup):
        s = rollup[article]
        gaps = ", ".join(s["gaps"]) if s["gaps"] else "-"
        lines.append(
            f"| {article} | {s['covered']} | {gaps} | {s['not_tested']} | "
            f"{', '.join(sorted(s['iso']))} | {', '.join(sorted(s['nist']))} |"
        )
    lines.append("")
    return lines


def _by_owasp_code(results, axis: str) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for r in results:
        code = getattr(controls_for(r), axis)
        if code:
            grouped.setdefault(code, []).append(r)
    return grouped


def _owasp_lines(results, *, axis: str, title: str, column: str) -> list[str]:
    lines = [f"## By {title}", "", f"| {column} | Tests | Status |", "|---|---|---|"]
    grouped = _by_owasp_code(results, axis)
    for code in sorted(grouped):
        rs = grouped[code]
        failed = [r.test_id for r in rs if r.status in (Status.failed, Status.error)]
        covered = any(r.status == Status.passed for r in rs)
        status = "gap" if failed else ("covered" if covered else "not tested")
        lines.append(f"| {code} | {', '.join(r.test_id for r in rs)} | {status} |")
    lines.append("")
    return lines


def to_compliance(run: RunResult, score: ScoreReport) -> str:
    results = run.results
    critical_fail = [
        r
        for r in results
        if r.risk.value == "critical" and r.status in (Status.failed, Status.error)
    ]

    lines = [
        f"# EU AI Act readiness evidence - {run.agent_name}",
        "",
        f"> {_DISCLAIMER}",
        "",
        "| Overall | Critical failures | Gate |",
        "|---|---|---|",
        f"| {score.overall_score * 100:.0f}% | {len(critical_fail)} | "
        f"{'INCOMPLETE' if score.incomplete else ('PASS' if score.gate_passed else 'BLOCK')} |",
        "",
    ]

    if score.incomplete:
        lines += [
            "**Run is INCOMPLETE** - no observed evidence (empty or all-skipped). "
            "This cannot satisfy any obligation.",
            "",
        ]

    lines += _critical_fail_lines(critical_fail)
    lines += _article_rollup_lines(results)
    lines += _owasp_lines(results, axis="owasp", title="OWASP Agentic Top 10", column="ASI")
    lines += _owasp_lines(results, axis="owasp_llm", title="OWASP LLM Top 10", column="LLM")

    lines += ["## Not tested (documented gaps)", ""]
    for code, reason in UNCOVERED:
        lines.append(f"- **{code}** - {reason}")
    lines.append("")

    return "\n".join(lines)


def to_compliance_json(run: RunResult, score: ScoreReport) -> str:
    payload = {
        "agent": run.agent_name,
        "run_id": run.run_id,
        "incomplete": score.incomplete,
        "gate_passed": score.gate_passed,
        "overall_score": score.overall_score,
        "articles": {},
        "owasp": {},
        "owasp_llm": {},
        "not_tested": [{"code": c, "reason": reason} for c, reason in UNCOVERED],
        "disclaimer": _DISCLAIMER,
    }
    for article, s in _rollup(run.results).items():
        payload["articles"][article] = {
            "covered": s["covered"],
            "gaps": s["gaps"],
            "not_tested": s["not_tested"],
            "iso_42001": sorted(s["iso"]),
            "nist_ai_rmf": sorted(s["nist"]),
        }
    for axis in ("owasp", "owasp_llm"):
        for code, rs in _by_owasp_code(run.results, axis).items():
            payload[axis][code] = {
                "tests": [r.test_id for r in rs],
                "gaps": [r.test_id for r in rs if r.status in (Status.failed, Status.error)],
            }
    return json.dumps(payload, indent=2)
