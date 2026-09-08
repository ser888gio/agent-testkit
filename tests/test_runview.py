"""The dashboard's derivation, tested as function calls.

Every case here used to require a TestClient, a seeded SQLite file and a
string-match against rendered HTML, because the derivation lived inside the
FastAPI handlers. That is the whole point of `core/runview.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentaudit.core import runview
from agentaudit.core.schema import (
    AssertionResult,
    Category,
    Risk,
    RunResult,
    Status,
    TestCase,
    TestResult,
)
from agentaudit.core.store import RunRow

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _run_row(run_id, *, status="passed", by_status=None, critical=0, agent="agent-a"):
    by_status = by_status or {"passed": 3}
    return RunRow(
        id=run_id,
        agent_id=agent,
        started_at=NOW.isoformat(),
        finished_at=(NOW + timedelta(seconds=5)).isoformat(),
        status=status,
        summary={"by_status": by_status},
        score={"overall_score": 0.5, "pass_rate": 0.5, "critical_failures": critical},
    )


def _result(test_id, status, *, category=Category.prompt_injection, risk=Risk.low, detail=""):
    return TestResult(
        test_id=test_id,
        category=category,
        risk=risk,
        status=status,
        started_at=NOW,
        finished_at=NOW + timedelta(milliseconds=10),
        latency_ms=10.0,
        error="not applicable" if status is Status.skipped else None,
        assertion_results=[
            AssertionResult(name="a", passed=status is Status.passed, detail=detail)
        ],
    )


def _run(results):
    return RunResult(
        run_id="r1",
        agent_name="agent-a",
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
        results=results,
    )


# --- dashboard --------------------------------------------------------------


def test_dashboard_views_each_row_once():
    """`_runs_page` used to call list_runs twice and build every view twice.

    A generator argument is consumed exactly once, so this fails loudly if the
    double pass ever comes back.
    """
    rows = iter([_run_row("a"), _run_row("b")])
    view = runview.dashboard(rows)
    assert len(view["all_runs"]) == 2


def test_dashboard_puts_runs_needing_attention_first():
    view = runview.dashboard(
        [_run_row("clean"), _run_row("bad", status="failed"), _run_row("crit", critical=2)]
    )
    assert [r["id"] for r in view["runs"]][:2] == ["crit", "bad"]
    assert [r["id"] for r in view["attention"]] == ["crit", "bad"]


def test_dashboard_stats_describe_the_unfiltered_set():
    """A filtered average would move as the reader typed, which reads as data changing."""
    rows = [_run_row("a", agent="one"), _run_row("b", status="failed", agent="two")]
    filtered = runview.dashboard(rows, agent="one")
    assert [r["id"] for r in filtered["runs"]] == ["a"]
    assert filtered["stats"]["total_runs"] == 2
    assert filtered["stats"]["failed_runs"] == 1


def test_dashboard_status_filter_matches_any_test_in_the_run():
    """A run's own status is a rollup; `skipped` only ever appears per-test."""
    rows = [_run_row("has-skip", by_status={"passed": 1, "skipped": 1}), _run_row("clean")]
    view = runview.dashboard(rows, status="skipped")
    assert [r["id"] for r in view["runs"]] == ["has-skip"]


# --- library ----------------------------------------------------------------


def _authored(pack_id, test_id, category="reliability", risk="low"):
    return {
        "pack_id": pack_id,
        "test_id": test_id,
        "category": category,
        "risk": risk,
        "created_by": None,
        "created_by_email": None,
    }


def test_authored_duplicate_ids_from_different_packs_remain_distinct():
    """Test ids are unique only within a pack, so two packs must not collapse."""
    rows = runview.library(
        [],
        [_authored("one", "shared.id"), _authored("two", "shared.id", "prompt_injection", "high")],
        [],
    )
    assert {(r["pack_id"], r["test_id"]) for r in rows} == {
        ("one", "shared.id"),
        ("two", "shared.id"),
    }


def test_authored_test_shows_before_it_has_ever_run():
    rows = runview.library([], [_authored("user", "new.test")], [])
    assert rows[0]["latest_status"] == runview.NEVER_RUN
    assert rows[0]["authored"] is True


def test_history_attaches_only_when_one_test_owns_the_id():
    """An ambiguous id gets its own unpacked row rather than picking a winner."""
    observed = [{"test_id": "shared.id", "latest_status": "failed", "run_count": 2}]
    rows = runview.library(
        [], [_authored("one", "shared.id"), _authored("two", "shared.id")], observed
    )
    by_pack = {r["pack_id"]: r for r in rows}
    assert by_pack[None]["latest_status"] == "failed"
    assert by_pack["one"]["latest_status"] == runview.NEVER_RUN


def test_shipped_pack_is_overwritten_by_authored_test_of_same_id():
    shipped = [
        (
            "core",
            TestCase(
                id="dup.id",
                input="hello",
                category=Category.prompt_injection,
                risk=Risk.high,
                assertions=[{"name": "contains", "args": {"value": "x"}}],
            ),
        )
    ]
    rows = runview.library(shipped, [_authored("core", "dup.id")], [])
    assert len(rows) == 1
    assert rows[0]["authored"] is True


def test_sort_library_puts_failures_first_and_never_run_last():
    rows = [
        {"test_id": "c", "latest_status": runview.NEVER_RUN, "risk": "critical", "category": "x"},
        {"test_id": "a", "latest_status": "failed", "risk": "low", "category": "x"},
        {"test_id": "b", "latest_status": "passed", "risk": "critical", "category": "x"},
    ]
    assert [r["test_id"] for r in runview.sort_library(rows)] == ["a", "b", "c"]


# --- run detail -------------------------------------------------------------


def test_detail_orders_failures_first():
    run = _run(
        [
            _result("t.pass", Status.passed),
            _result("t.fail", Status.failed),
            _result("t.skip", Status.skipped),
            _result("t.error", Status.error),
        ]
    )
    view = runview.detail(run)
    assert [r["test_id"] for r in view["result_rows"]] == [
        "t.error",
        "t.fail",
        "t.pass",
        "t.skip",
    ]
    assert {r["test_id"] for r in view["failures"]} == {"t.fail", "t.error"}


def test_detail_filter_narrows_rows_but_not_the_matrix():
    """The category matrix is a map of the whole run, not of the current filter."""
    run = _run(
        [
            _result("sec.a", Status.failed, category=Category.prompt_injection),
            _result("rel.a", Status.passed, category=Category.reliability),
        ]
    )
    view = runview.detail(run, category="prompt_injection")
    assert [r["test_id"] for r in view["result_rows"]] == ["sec.a"]
    assert set(view["categories"]) == {"prompt_injection", "reliability"}


# --- harness ----------------------------------------------------------------


def test_harness_findings_stay_in_run_order():
    """The harness page is read as a transcript, so step numbering must be chronological."""
    run = _run([_result("t.fail", Status.failed), _result("t.pass", Status.passed)])
    from agentaudit.core.scoring import score

    view = runview.harness(run, score(run))
    assert [f["step"] for f in view["findings"]] == [1, 2]
    assert [f["test_id"] for f in view["findings"]] == ["t.fail", "t.pass"]


def test_harness_summary_blocks_on_critical_failure():
    run = _run([_result("t.fail", Status.failed, risk=Risk.critical)])
    from agentaudit.core.scoring import score

    view = runview.harness(run, score(run))
    assert view["summary"]["gate"] == "BLOCK"
    assert view["summary"]["critical_failures"] == 1


# --- analytics --------------------------------------------------------------


def test_analytics_delta_is_zero_for_a_single_run():
    """One run has no trend to move; a delta against itself is the honest answer."""
    view = runview.analytics([{"score": 72}], [_run_row("r1")])
    assert view["totals"]["latest_score"] == 72
    assert view["totals"]["delta"] == 0


def test_analytics_delta_compares_the_two_most_recent_scores():
    trend = [{"score": 40}, {"score": 55}, {"score": 51}]
    view = runview.analytics(trend, [_run_row("r1")])
    assert view["totals"]["latest_score"] == 51
    assert view["totals"]["delta"] == -4


def test_analytics_on_an_empty_org_does_not_divide_by_zero():
    view = runview.analytics([], [])
    assert view["totals"] == {
        "runs": 0,
        "agents": 0,
        "gate_rate": 0,
        "critical": 0,
        "latest_score": 0,
        "delta": 0,
    }


def test_analytics_gate_rate_counts_runs_that_are_not_failed_or_error():
    rows = [
        _run_row("r1", status="passed"),
        _run_row("r2", status="failed"),
        _run_row("r3", status="error"),
        _run_row("r4", status="passed"),
    ]
    view = runview.analytics([], rows)
    assert view["totals"]["gate_rate"] == 50
    assert view["totals"]["runs"] == 4


def test_analytics_counts_distinct_agents_not_runs():
    rows = [
        _run_row("r1", agent="agent-a"),
        _run_row("r2", agent="agent-a"),
        _run_row("r3", agent="agent-b"),
    ]
    assert runview.analytics([], rows)["totals"]["agents"] == 2


# --- test_detail ------------------------------------------------------------


def test_test_detail_neighbours_follow_the_failure_first_order():
    run = _run(
        [
            _result("t.pass", Status.passed),
            _result("t.fail", Status.failed),
            _result("t.error", Status.error),
        ]
    )
    # Failure-first order is error, fail, pass -- so `t.fail` sits between them.
    view = runview.test_detail(run, run.results[1])
    assert view["previous_result"].test_id == "t.error"
    assert view["next_result"].test_id == "t.pass"


def test_test_detail_ends_have_no_neighbour_on_the_outside():
    run = _run([_result("t.error", Status.error), _result("t.pass", Status.passed)])
    first = runview.test_detail(run, run.results[0])
    last = runview.test_detail(run, run.results[1])
    assert first["previous_result"] is None
    assert last["next_result"] is None


def test_test_detail_of_a_lone_result_has_neither_neighbour():
    run = _run([_result("t.only", Status.passed)])
    view = runview.test_detail(run, run.results[0])
    assert view["previous_result"] is None and view["next_result"] is None


def test_test_detail_reports_no_timeline_for_a_single_turn():
    """One request and one reply is not a sequence worth drawing."""
    run = _run([_result("t.a", Status.passed)])
    assert runview.test_detail(run, run.results[0])["timeline"] is None
    states = {
        a["name"]: a["state"] for a in runview.test_detail(run, run.results[0])["artifact_states"]
    }
    assert states["Timeline"] == "Unavailable"
    assert states["Sandbox diff"] == "Empty"


def test_test_detail_variant_inherits_its_base_test_rationale():
    """A transform changed how the test asks, not why it was selected."""
    from agentaudit.core.profile import AgentProfile, HarnessPlan, SelectedTest

    run = _run([_result("t.base__rot13", Status.failed)])
    plan = HarnessPlan(
        profile=AgentProfile(id="agent-a"),
        selected=[SelectedTest(test_id="t.base", source="pack", score=1.0, reasons=["seeded"])],
    )
    view = runview.test_detail(run, run.results[0], plan=plan)
    assert view["selection"] is not None
    assert view["selection"].test_id == "t.base"


def test_test_detail_without_a_plan_has_no_selection():
    run = _run([_result("t.a", Status.passed)])
    assert runview.test_detail(run, run.results[0])["selection"] is None


def test_harness_reconciles_step_count_with_scored_total():
    """A skipped step is shown but never scored; the page must say so.

    Without `unscored`/`steps` the summary shows N steps over a smaller
    denominator ("3 steps, 0 of 2 tests") and reads as an arithmetic bug.
    """
    from agentaudit.core.scoring import score

    run = _run(
        [
            _result("t.pass", Status.passed),
            _result("t.fail", Status.failed),
            _result("t.skip", Status.skipped),
        ]
    )
    view = runview.harness(run, score(run))

    assert view["summary"]["steps"] == 3
    assert view["summary"]["total"] == 2  # skipped is not scored
    assert view["summary"]["unscored"] == 1
    assert [f["scored"] for f in view["findings"]] == [True, True, False]


def test_harness_counts_errored_steps_separately():
    """An unreachable agent and a misbehaving one must not read the same."""
    from agentaudit.core.scoring import score

    run = _run([_result("t.err", Status.error, risk=Risk.critical)])
    view = runview.harness(run, score(run))

    assert view["summary"]["errored"] == 1
    assert view["summary"]["gate"] == "BLOCK"


def test_harness_step_reports_only_the_evidence_it_has():
    """A timed-out step must not advertise evidence behind its link."""
    from agentaudit.core.scoring import score

    run = _run([_result("t.err", Status.error)])
    (finding,) = runview.harness(run, score(run))["findings"]

    assert finding["evidence"] == {
        "request": False,
        "response": False,
        "sandbox_diff": False,
        "events": 0,
        "timeline": False,
    }


def test_harness_step_evidence_matches_what_the_evidence_page_renders():
    """The badge must not promise a timeline `test_detail` then declines to draw.

    Both apply the same >= 2 turn bar; asserting them together is what stops
    the two from drifting apart.
    """
    from agentaudit.core.scoring import score

    result = _result("t.multi", Status.failed)
    result.request = ["turn one", "turn two"]
    result.response = "final reply"
    result.sandbox_diff = {"bank": {"payments": 1}}
    run = _run([result])

    (finding,) = runview.harness(run, score(run))["findings"]
    assert finding["evidence"]["request"] is True
    assert finding["evidence"]["response"] is True
    assert finding["evidence"]["sandbox_diff"] is True
    assert finding["evidence"]["timeline"] is True
    assert runview.test_detail(run, result)["timeline"] is not None


def test_harness_step_hides_timeline_badge_for_a_single_turn():
    """One turn is a request and a reply, not a sequence worth drawing."""
    from agentaudit.core.scoring import score

    result = _result("t.single", Status.failed)
    result.request = "just the one turn"
    run = _run([result])

    (finding,) = runview.harness(run, score(run))["findings"]
    assert finding["evidence"]["timeline"] is False
    assert runview.test_detail(run, result)["timeline"] is None
