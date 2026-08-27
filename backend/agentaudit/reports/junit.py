"""JUnit XML report: consumable by standard CI parsers."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from agentaudit.core.findings import detail_for, order_by_failure
from agentaudit.core.schema import RunResult, Status
from agentaudit.core.scoring import ScoreReport
from agentaudit.core.timeline import build as build_timeline
from agentaudit.core.timeline import to_lines as timeline_lines
from agentaudit.core.timeline import window as window_timeline


def to_junit(run: RunResult, score: ScoreReport) -> str:
    results = run.results
    failures = sum(1 for r in results if r.status == Status.failed)
    errors = sum(1 for r in results if r.status == Status.error)
    skipped = sum(1 for r in results if r.status == Status.skipped)
    total_time = sum((r.latency_ms or 0) for r in results) / 1000

    suite = ET.Element(
        "testsuite",
        {
            "name": "agentaudit",
            "tests": str(len(results)),
            "failures": str(failures),
            "errors": str(errors),
            "skipped": str(skipped),
            "time": f"{total_time:.3f}",
        },
    )

    ordered = order_by_failure(results)
    for r in ordered:
        tc = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": r.category.value,
                "name": r.test_id,
                "time": f"{(r.latency_ms or 0) / 1000:.3f}",
            },
        )
        if r.status == Status.failed:
            detail = detail_for(r) or "assertion failed"
            ET.SubElement(tc, "failure", {"message": detail})
        elif r.status == Status.error:
            ET.SubElement(tc, "error", {"message": r.error or "error"})
        elif r.status == Status.skipped:
            ET.SubElement(tc, "skipped")

        if r.status in (Status.failed, Status.error):
            timeline = window_timeline(build_timeline(r))
            if len(timeline["turns"]) >= 2:
                out = ET.SubElement(tc, "system-out")
                out.text = "\n".join(timeline_lines(timeline))

    return ET.tostring(suite, encoding="unicode")
