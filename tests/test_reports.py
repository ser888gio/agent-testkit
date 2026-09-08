import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

from agentaudit.core.profile import AgentProfile, ExcludedTest, HarnessPlan, SelectedTest
from agentaudit.core.schema import (
    AssertionResult,
    Category,
    Risk,
    RunResult,
    SandboxEvent,
    Status,
    TestResult,
)
from agentaudit.core.scoring import score
from agentaudit.reports import (
    FORMATS,
    render,
    to_coverage,
    to_html,
    to_json,
    to_junit,
    to_markdown,
    to_pdf,
    to_plan_markdown,
)


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
            error="requires sandbox, none configured",
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


def _variant(test_id: str, detail: str) -> TestResult:
    return TestResult(
        test_id=test_id,
        category=Category.prompt_injection,
        risk=Risk.high,
        status=Status.failed,
        assertion_results=[AssertionResult(name="no_payment_created", passed=False, detail=detail)],
        started_at=_now(),
        finished_at=_now(),
    )


def test_to_markdown_groups_attack_variants():
    rr = _run()
    rr.results += [
        _variant("e.inject.payee__base64", "paid INV-90"),
        _variant("e.inject.payee__leetspeak", "paid INV-91"),
    ]
    md = to_markdown(rr, score(rr))

    assert "- ❌ e.inject.payee — 2 attack(s) bypassed" in md
    assert "  - base64: paid INV-90" in md
    assert "  - leetspeak: paid INV-91" in md
    # Plain failures keep the single-line form.
    assert "- ❌ b.fail.case: found 1 payment" in md


def test_to_markdown_names_the_attacker_technique_and_degradation():
    rr = _run()
    landed = _variant("e.inject.payee", "paid INV-90")
    landed.techniques = ["response_priming"]
    fell_back = _variant("e.inject.other", "paid INV-91")
    fell_back.degraded = True
    rr.results += [landed, fell_back]
    md = to_markdown(rr, score(rr))

    assert "- ❌ e.inject.payee: paid INV-90 (via response_priming)" in md
    # A degraded run must never read as a model-driven probe.
    assert "- ❌ e.inject.other: paid INV-91 (degraded to scripted ladder)" in md
    # A scripted result gains no suffix at all.
    assert "- ❌ b.fail.case: found 1 payment" in md


def test_to_markdown_unchanged_without_variants(run_and_score):
    rr, report = run_and_score
    # Only the failures block: sections after it (skipped, trial policies) are
    # covered by their own tests, and asserting on the tail made this test fail
    # whenever an unrelated section was added.
    md = to_markdown(rr, report)
    failures = md.split("## Failures\n\n")[1].split("\n\n##")[0]
    assert failures == "- \u274c b.fail.case: found 1 payment\n- \u274c c.error.case: timeout"


def test_to_markdown_has_no_trial_section_without_trial_results(run_and_score):
    rr, report = run_and_score
    assert "## Trial policies" not in to_markdown(rr, report)


def test_to_markdown_shows_trial_n_pass_rate_and_threshold():
    result = TestResult(
        test_id="trial.flaky.case",
        category=Category.reliability,
        risk=Risk.medium,
        status=Status.passed,
        attempts=[Status.passed, Status.failed, Status.passed, Status.passed],
        trial_threshold=0.75,
        started_at=_now(),
        finished_at=_now(),
    )
    rr = RunResult(
        run_id="r2", agent_name="demo", started_at=_now(), finished_at=_now(), results=[result]
    )
    md = to_markdown(rr, score(rr))
    assert "## Trial policies" in md
    assert "| trial.flaky.case | 4 | 75% | 75% | 3 |" in md
    assert "Total trial cost: +3 agent call(s)" in md


def test_render_dispatches_by_format(run_and_score):
    rr, report = run_and_score
    assert render(rr, report, "json") == to_json(rr, report)
    assert render(rr, report, "junit") == to_junit(rr, report)


def test_render_unknown_format_raises():
    rr = _run()
    report = score(rr)
    with pytest.raises(ValueError, match="unknown report format"):
        render(rr, report, "yaml")


def _plan() -> HarnessPlan:
    return HarnessPlan(
        profile=AgentProfile(
            id="treasury-agent",
            domain="treasury",
            sandbox="treasury",
            tool_use=True,
            side_effects=["money_movement"],
            notes=["answered a trivial probe in 12 ms"],
        ),
        selected=[
            SelectedTest(
                test_id="core.prompt_injection.instruction_override",
                source="local",
                score=3.25,
                reasons=["written for the treasury domain", "risk high"],
            )
        ],
        excluded=[
            ExcludedTest(
                test_id="promptfoo.pii",
                source="promptfoo",
                reason="promptfoo is not installed on this runner",
            )
        ],
        attack_transforms=["base64"],
    )


def test_plan_report_covers_profile_selection_and_untested_areas():
    out = to_plan_markdown(_plan())

    assert "# agentaudit plan - treasury-agent" in out
    assert "answered a trivial probe in 12 ms" in out
    assert "written for the treasury domain" in out
    assert "## Not tested (1)" in out
    assert "promptfoo is not installed on this runner" in out
    assert "base64" in out


def test_plan_report_says_so_when_there_is_no_plan():
    assert "without a planner" in to_plan_markdown(None)


def test_plan_report_flags_selections_this_run_did_not_execute():
    plan = _plan()
    plan.selected.append(
        SelectedTest(test_id="garak.dan", source="garak", score=2.0, reasons=["risk high"])
    )

    out = to_plan_markdown(plan)

    assert "executed by an external tool" in out
    assert "garak.dan" in out


def _origin_run() -> RunResult:
    def _r(test_id, category=Category.action_safety, status=Status.passed):
        return TestResult(
            test_id=test_id,
            category=category,
            risk=Risk.high,
            status=status,
            started_at=_now(),
            finished_at=_now(),
        )

    return RunResult(
        run_id="cov",
        agent_name="demo",
        started_at=_now(),
        finished_at=_now(),
        results=[
            _r("treasury.over_limit.blocked"),
            _r("generated.tool_misuse.abc123__base64", status=Status.failed),
            _r("promoted.tool_misuse.def456"),
        ],
    )


def test_coverage_separates_reviewed_from_machine_authored_evidence():
    rr = _origin_run()
    out = to_coverage(rr, score(rr))
    assert "| Hand-authored | 1 | yes |" in out
    assert "| Promoted | 1 | yes, by a human |" in out
    assert "| Generated | 1 | **no - provisional** |" in out
    # An unreviewed test must not read as a reviewed control.
    assert "no human has reviewed" in out


def test_coverage_names_the_cells_that_were_not_probed():
    rr = _origin_run()
    out = to_coverage(rr, score(rr))
    assert "## Not probed" in out
    assert "An unprobed cell is not a pass" in out
    # base64 was probed, so it must not appear as missing for that category.
    missing = out.split("## Not probed")[1]
    assert "rot13" in missing


def test_coverage_reports_the_style_each_result_exercised():
    rr = _origin_run()
    out = to_coverage(rr, score(rr))
    assert "| action_safety | base64 | 1 | 1 |" in out
    assert "| action_safety | plain | 2 | 0 |" in out


def test_a_run_with_no_generated_tests_carries_no_provisional_warning():
    rr = RunResult(
        run_id="cov",
        agent_name="demo",
        started_at=_now(),
        finished_at=_now(),
        results=[
            TestResult(
                test_id="treasury.over_limit.blocked",
                category=Category.action_safety,
                risk=Risk.high,
                status=Status.passed,
                started_at=_now(),
                finished_at=_now(),
            )
        ],
    )
    out = to_coverage(rr, score(rr))
    assert "no human has reviewed" not in out


def test_coverage_is_reachable_through_render(run_and_score):
    rr, report = run_and_score
    assert render(rr, report, "coverage") == to_coverage(rr, report)


def test_plan_is_a_format_like_any_other():
    """`plan` used to sit outside `render`, so every caller branched on it."""
    assert "plan" in FORMATS
    assert render(_run(), score(_run()), "plan", plan=None).startswith("This run was launched")


def test_unknown_format_lists_plan_among_the_valid_ones():
    with pytest.raises(ValueError, match="plan"):
        render(_run(), score(_run()), "nope")


def test_render_ignores_plan_for_result_formats():
    """The six renderers that predate the argument must not see it."""
    rr = _run()
    assert render(rr, score(rr), "json") == render(rr, score(rr), "json", plan=None)


# --- PRD-011: step-level timelines ------------------------------------------


def _multi_turn_failure() -> TestResult:
    now = _now()
    return TestResult(
        test_id="f.memory.poisoned",
        category=Category.memory_context,
        risk=Risk.critical,
        status=Status.failed,
        request=["plant poison", "cash it in"],
        response={"text": "paid"},
        assertion_results=[
            AssertionResult(name="no_payment_created", passed=False, detail="found 1 payment")
        ],
        events=[
            SandboxEvent(kind="agent.turn", data={"text": "plant poison"}, ts=now),
            SandboxEvent(kind="agent.turn", data={"text": "cash it in"}, ts=now),
            SandboxEvent(kind="payment.created", data={"invoice_id": "INV-1"}, ts=now),
        ],
        started_at=now,
        finished_at=now,
    )


@pytest.fixture
def multi_turn_run_and_score():
    rr = _run()
    rr.results.append(_multi_turn_failure())
    return rr, score(rr)


def test_json_report_carries_an_optional_timeline_block(multi_turn_run_and_score):
    rr, report = multi_turn_run_and_score
    payload = json.loads(to_json(rr, report))
    results = {r["test_id"]: r for r in payload["run"]["results"]}
    # Single-turn results carry no `timeline` key at all -- additive, not a
    # new required field existing consumers must handle.
    assert "timeline" not in results["a.pass.case"]
    timeline = results["f.memory.poisoned"]["timeline"]
    assert timeline["first_divergence"] == 1
    assert [t["input"] for t in timeline["turns"]] == ["plant poison", "cash it in"]


def test_markdown_report_renders_timeline_for_failing_multi_turn_test(
    multi_turn_run_and_score,
):
    rr, report = multi_turn_run_and_score
    md = to_markdown(rr, report)
    assert "Turn 0: plant poison" in md
    assert "Turn 1: cash it in <-- first divergence" in md


def test_html_report_renders_timeline_for_failing_multi_turn_test(multi_turn_run_and_score):
    rr, report = multi_turn_run_and_score
    html = to_html(rr, report)
    assert "Turn 0: plant poison" in html
    assert "diverges" in html
    assert "payment.created" in html


def test_junit_report_attaches_timeline_as_system_out(multi_turn_run_and_score):
    rr, report = multi_turn_run_and_score
    xml_text = to_junit(rr, report)
    root = ET.fromstring(xml_text)
    tc = next(tc for tc in root.findall("testcase") if tc.attrib["name"] == "f.memory.poisoned")
    system_out = tc.find("system-out")
    assert system_out is not None
    assert "Turn 0: plant poison" in system_out.text
    assert "first divergence" in system_out.text


def test_single_turn_results_render_no_timeline_section(run_and_score):
    """Parity guard: a single-turn failure gets no timeline noise anywhere."""
    rr, report = run_and_score
    assert "Timeline" not in to_markdown(rr, report)
    assert "<h4>Timeline</h4>" not in to_html(rr, report)
    xml_text = to_junit(rr, report)
    root = ET.fromstring(xml_text)
    for tc in root.findall("testcase"):
        assert tc.find("system-out") is None


def _pdf_text(rr, report) -> str:
    """Drawn text of a rendered PDF, in order.

    Page streams are Flate-compressed by default, so the assertions below would
    have nothing to match. Turning compression off makes the content stream
    plain ASCII; it changes only this fixture's bytes, not the shipped renderer.
    """
    import reportlab.rl_config as rl_config

    previous = rl_config.pageCompression
    rl_config.pageCompression = 0
    try:
        data = to_pdf(rr, report)
    finally:
        rl_config.pageCompression = previous
    runs = re.findall(r"\((?:\.|[^\()])*\)", data.decode("latin-1"))
    return "\n".join(run[1:-1] for run in runs)


def test_pdf_report_is_a_valid_pdf(run_and_score):
    rr, report = run_and_score
    data = to_pdf(rr, report)
    assert isinstance(data, bytes)
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data[-2048:]


def test_pdf_report_renders_score_and_failures(run_and_score):
    """The PDF must agree with the Markdown report; a blank but structurally
    valid PDF would otherwise pass the header check above."""
    rr, report = run_and_score
    text = _pdf_text(rr, report)
    assert "agentaudit report - demo" in text
    assert "BLOCK" in text
    for test_id in ("b.fail.case", "c.error.case"):
        assert test_id in text
    assert "found 1 payment" in text
    # Every test appears in the "All tests" table, not just the failures.
    assert "a.pass.case" in text
    assert "d.skip.case" in text


def test_pdf_report_escapes_markup_in_evidence(run_and_score):
    """Platypus parses a mini-markup, so an unescaped `<` in a test id would
    raise at build time rather than render."""
    rr, report = run_and_score
    rr.results[0].test_id = "a.<b>&.case"
    data = to_pdf(rr, report)
    assert data.startswith(b"%PDF-")
