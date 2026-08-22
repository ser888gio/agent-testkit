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
