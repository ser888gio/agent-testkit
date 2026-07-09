"""JUnit XML report: consumable by standard CI parsers."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from agentkit.core.schema import RunResult, Status
from agentkit.core.scoring import ScoreReport

_FAILURE_RANK = {Status.failed: 0, Status.error: 0, Status.passed: 1, Status.skipped: 2}


def _first_failing_detail(results) -> str:
    for a in results:
        if not a.passed:
            return a.detail
    return ""


def to_junit(run: RunResult, score: ScoreReport) -> str:
    results = run.results
    failures = sum(1 for r in results if r.status == Status.failed)
    errors = sum(1 for r in results if r.status == Status.error)
    skipped = sum(1 for r in results if r.status == Status.skipped)
    total_time = sum((r.latency_ms or 0) for r in results) / 1000

    suite = ET.Element(
        "testsuite",
        {
            "name": "agentkit",
            "tests": str(len(results)),
            "failures": str(failures),
            "errors": str(errors),
            "skipped": str(skipped),
            "time": f"{total_time:.3f}",
        },
    )

    ordered = sorted(results, key=lambda r: (_FAILURE_RANK.get(r.status, 1), r.test_id))
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
            detail = _first_failing_detail(r.assertion_results) or "assertion failed"
            ET.SubElement(tc, "failure", {"message": detail})
        elif r.status == Status.error:
            ET.SubElement(tc, "error", {"message": r.error or "error"})
        elif r.status == Status.skipped:
            ET.SubElement(tc, "skipped")

    return ET.tostring(suite, encoding="unicode")
