import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

from agentkit.core.schema import (
    AssertionResult,
    Category,
    Risk,
    RunResult,
    Status,
    TestResult,
)
from agentkit.core.scoring import score
from agentkit.reports import render, to_html, to_json, to_junit, to_markdown


def _now():
    return datetime.now(timezone.utc)


def _run() -> RunResult:
    results = [
        TestResult(
            test_id="a.pass.case",
            category=Category.reliability,
            risk=Risk.low,
            status=Status.passed,
            latency_ms=10.0,
            assertion_results=[AssertionResult(name="status_ok", passed=True)],
            request={"input": "hi"},
            response={"text": "ok"},
            started_at=_now(),
            finished_at=_now(),
        ),
        TestResult(
            test_id="b.fail.case",
            category=Category.action_safety,
            risk=Risk.critical,
            status=Status.failed,
            latency_ms=20.0,
            assertion_results=[
                AssertionResult(
                    name="no_payment_created", passed=False, detail="found 1 payment"
                )
            ],
            request={"input": "pay now"},
            response={"text": "«redacted:api_key» paid"},
            started_at=_now(),
            finished_at=_now(),
        ),
        TestResult(
            test_id="c.error.case",
            category=Category.performance,
            risk=Risk.medium,
            status=Status.error,
            latency_ms=None,
            error="timeout",
            started_at=_now(),
            finished_at=_now(),
        ),
        TestResult(
            test_id="d.skip.case",
            category=Category.reliability,
            risk=Risk.low,
            status=Status.skipped,
            latency_ms=None,
            started_at=_now(),
            finished_at=_now(),
        ),
    ]
    return RunResult(
        run_id="r1",
        agent_name="demo",
        started_at=_now(),
        finished_at=_now(),
        results=results,
    )


@pytest.fixture
def run_and_score():
    rr = _run()
    return rr, score(rr)


def test_to_json_structural(run_and_score):
    rr, report = run_and_score
    payload = json.loads(to_json(rr, report))
    assert payload["run"]["run_id"] == "r1"
    assert payload["score"]["critical_failures"] == report.critical_failures
    assert len(payload["run"]["results"]) == 4


def test_to_junit_parses_and_counts_match(run_and_score):
    rr, report = run_and_score
    xml_text = to_junit(rr, report)
    root = ET.fromstring(xml_text)
    assert root.tag == "testsuite"
    assert root.attrib["tests"] == "4"
    assert root.attrib["failures"] == "1"
    assert root.attrib["errors"] == "1"
    assert root.attrib["skipped"] == "1"

    testcases = root.findall("testcase")
    assert len(testcases) == 4
    by_name = {tc.attrib["name"]: tc for tc in testcases}
    assert by_name["b.fail.case"].find("failure").attrib["message"] == "found 1 payment"
    assert by_name["c.error.case"].find("error").attrib["message"] == "timeout"
    assert by_name["d.skip.case"].find("skipped") is not None
    assert by_name["a.pass.case"].find("failure") is None


def test_to_html_self_contained_and_shows_redacted(run_and_score):
    rr, report = run_and_score
    html = to_html(rr, report)
    assert "http://" not in html
    assert "https://" not in html
    assert "b.fail.case" in html
    assert "«redacted:api_key»" in html


def test_to_markdown_lists_failures_with_detail(run_and_score):
    rr, report = run_and_score
    md = to_markdown(rr, report)
    assert "b.fail.case: found 1 payment" in md
    assert "c.error.case: timeout" in md
    assert "a.pass.case" not in md.split("## Failures")[1]


def test_render_dispatches_by_format(run_and_score):
    rr, report = run_and_score
    assert render(rr, report, "json") == to_json(rr, report)
    assert render(rr, report, "junit") == to_junit(rr, report)


def test_render_unknown_format_raises():
    rr = _run()
    report = score(rr)
    with pytest.raises(ValueError, match="unknown report format"):
        render(rr, report, "yaml")
