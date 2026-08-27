"""PDF report: the same score summary and failure list as the Markdown and HTML
renderers, laid out for print.

Unlike its six siblings this returns `bytes`, not `str`, which is why it is not
in `reports/__init__.py:_RENDERERS` -- that registry is typed `-> str` and six
modules depend on it. Callers dispatch this one directly, the way `plan` is.
"""

from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from agentaudit.core.attacks import split_variant
from agentaudit.core.findings import detail_for, failures, order_by_failure, provenance_for
from agentaudit.core.schema import RunResult
from agentaudit.core.scoring import ScoreReport

# Muted palette: this is evidence, and a red row should mean something.
_INK = colors.HexColor("#101828")
_MUTED = colors.HexColor("#667085")
_LINE = colors.HexColor("#e4e7ec")
_FAIL = colors.HexColor("#b42318")
_PASS = colors.HexColor("#067647")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            alignment=TA_LEFT,
            textColor=_INK,
            spaceAfter=2,
        ),
        "sub": ParagraphStyle(
            "sub", parent=base["Normal"], fontSize=9, leading=12, textColor=_MUTED
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=_INK,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=9, leading=13, textColor=_INK
        ),
        "fail": ParagraphStyle(
            "fail",
            parent=base["Normal"],
            fontSize=9,
            leading=13,
            textColor=_FAIL,
            fontName="Helvetica-Bold",
        ),
        "detail": ParagraphStyle(
            "detail",
            parent=base["Normal"],
            fontSize=8.5,
            leading=12,
            textColor=_MUTED,
            leftIndent=10,
        ),
    }


def _summary_table(score: ScoreReport, st: dict) -> Table:
    gate = "PASS" if score.gate_passed else "BLOCK"
    cells = [
        ["Overall", "Pass rate", "Critical failures", "Gate"],
        [
            f"{score.overall_score * 100:.0f}%",
            f"{score.pass_rate * 100:.0f}%",
            str(score.critical_failures),
            gate,
        ],
    ]
    table = Table(cells, colWidths=[42 * mm] * 4, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 15),
                ("TEXTCOLOR", (0, 1), (-1, 1), _INK),
                # The gate is the number a reader looks for first.
                ("TEXTCOLOR", (3, 1), (3, 1), _PASS if score.gate_passed else _FAIL),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("LINEBELOW", (0, 1), (-1, 1), 0.5, _LINE),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
            ]
        )
    )
    return table


def _failure_flowables(run: RunResult, st: dict) -> list:
    """One entry per base test; attack variants roll up under it, mirroring
    `md.py:_failure_lines` so the two reports never disagree."""
    failing = failures(run.results)
    if not failing:
        return [Paragraph("No failures recorded.", st["body"])]

    grouped: dict[str, list[tuple[str | None, str]]] = {}
    for r in failing:
        base, transform = split_variant(r.test_id)
        provenance = provenance_for(r)
        detail = f"{detail_for(r)} ({provenance})" if provenance else detail_for(r)
        grouped.setdefault(base, []).append((transform, detail))

    out: list = []
    for base, entries in grouped.items():
        variants = [(t, d) for t, d in entries if t]
        block: list = []
        if not variants:
            block.append(Paragraph(_esc(base), st["fail"]))
            block.append(Paragraph(_esc(entries[0][1]), st["detail"]))
        else:
            block.append(
                Paragraph(f"{_esc(base)} - {len(variants)} attack(s) bypassed", st["fail"])
            )
            for transform, detail in entries:
                block.append(
                    Paragraph(f"{_esc(transform or 'original')}: {_esc(detail)}", st["detail"])
                )
        block.append(Spacer(1, 6))
        # Keep a finding and its details on one page; a split reads as two findings.
        out.append(KeepTogether(block))
    return out


def _results_table(run: RunResult, st: dict) -> Table:
    header = ["Test", "Category", "Risk", "Status"]
    rows = [header]
    ordered = order_by_failure(run.results)
    for r in ordered:
        rows.append(
            [
                Paragraph(_esc(r.test_id), st["body"]),
                _esc(r.category.value),
                _esc(r.risk.value),
                _esc(r.status.value),
            ]
        )

    table = Table(rows, colWidths=[76 * mm, 33 * mm, 25 * mm, 24 * mm], repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
    ]
    for i, r in enumerate(ordered, start=1):
        if r.status.value in ("failed", "error"):
            style.append(("TEXTCOLOR", (3, i), (3, i), _FAIL))
    table.setStyle(TableStyle(style))
    return table


def _esc(value: object) -> str:
    """Platypus parses a mini-markup, so `&`/`<`/`>` in evidence must be escaped
    or a test id containing them raises at build time."""
    return (
        str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(_MUTED)
    canvas.drawString(18 * mm, 12 * mm, "Generated by agentaudit - redacted evidence")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def to_pdf(run: RunResult, score: ScoreReport) -> bytes:
    st = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=f"agentaudit report - {run.agent_name}",
        author="agentaudit",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
    )

    story: list = [
        Paragraph(f"agentaudit report - {_esc(run.agent_name)}", st["title"]),
        Paragraph(_esc(run.run_id), st["sub"]),
        Spacer(1, 12),
        _summary_table(score, st),
        Paragraph("Failures", st["h2"]),
    ]
    story.extend(_failure_flowables(run, st))
    story.append(PageBreak())
    story.append(Paragraph("All tests", st["h2"]))
    story.append(_results_table(run, st))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
