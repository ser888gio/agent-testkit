"""Render-ready views of a run: the derivation the dashboard used to do inline.

Every page of the dashboard answers a question about a run -- which runs need
attention, which tests exist and how they last did, what one run's findings
were -- and each answer used to be derived inside its own FastAPI handler. That
put the whole derivation behind an HTTP round-trip: the only way to assert that
failures sort first, or that an authored test with no history still appears, was
to serve a page and read the HTML back.

Four things went wrong there and are fixed by giving the derivation an interface
of its own:

- The failure-first ordering was re-spelled in the web tier as a private
  `_STATUS_RANK`, alongside the `findings.order_by_failure` that already owned
  it. Two spellings of one rule, and `findings` was the one with the tests.
- `_runs_page` fetched `list_runs` twice and built every row view twice, which
  nothing noticed because the derivation was unreadable apart from the handler.
- Filtering, sorting and rollup could not be tested without a TestClient.
- Nothing named the concept, so each new page grew its own copy.

Nothing here does I/O. Callers fetch rows and pass them in, which is what keeps
the double-fetch impossible to reintroduce and lets the tests be ordinary
function calls. Control-plane only: these derive from an already-redacted
`RunResult` and never touch a live agent.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agentaudit.core.findings import RANK, failed_assertions, order_by_failure
from agentaudit.core.schema import Category, Status

# Statuses that mean a reader should look at this run.
BAD_STATUSES = frozenset({"failed", "error"})

# What the library page shows for a test that has never appeared in a run.
NEVER_RUN = "never run"

# `findings.RANK` keyed by the wire value, for rows that carry a status string
# rather than a `Status`. `NEVER_RUN` sorts last: it is the absence of evidence,
# not a result.
STATUS_RANK: dict[str, int] = {status.value: rank for status, rank in RANK.items()}
_NEVER_RUN_RANK = max(STATUS_RANK.values()) + 1

_RISK_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def pct(value: float | int | None) -> int:
    if value is None:
        return 0
    return int(float(value) * 100)


def short_date(value: Any) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value or "")
    return text[:16].replace("T", " ")


def duration_ms(started: Any, finished: Any) -> float | None:
    try:
        return max(0.0, (finished - started).total_seconds() * 1000)
    except TypeError:
        return None


def run_row(row: Any) -> dict:
    """One `Store.list_runs` row as the dashboard renders it."""
    score = row.score
    by_status = row.summary.get("by_status", {})
    failed = by_status.get("failed", 0) + by_status.get("error", 0)
    return {
        "row": row,
        "id": row.id,
        "short_id": row.id[:8],
        "agent_id": row.agent_id,
        "started": short_date(row.started_at),
        # CLI runs have no principal; show that rather than inventing one.
        "launched_by": row.created_by_email or row.created_by or "CLI",
        "finished": short_date(row.finished_at),
        "status": row.status,
        "by_status": by_status,
        "score_percent": pct(score.get("overall_score", 0)),
        "pass_percent": pct(score.get("pass_rate", 0)),
        "critical_failures": score.get("critical_failures", 0),
        "total": sum(by_status.values()),
        "failed": failed,
        "passed": by_status.get("passed", 0),
        "skipped": by_status.get("skipped", 0),
        "needs_attention": row.status in BAD_STATUSES or score.get("critical_failures", 0) > 0,
    }


def filter_rows(rows: list[dict], q: str = "", status: str = "all") -> list[dict]:
    """Free-text and exact-status filter shared by every table on the site."""
    q = q.strip().lower()
    filtered = []
    for row in rows:
        haystack = " ".join(
            str(row.get(k, "")) for k in ("id", "agent_id", "test_id", "category")
        ).lower()
        if q and q not in haystack:
            continue
        if status != "all" and row.get("status") != status:
            continue
        filtered.append(row)
    return filtered


def filter_run_rows(rows: list[dict], q: str = "", status: str = "all") -> list[dict]:
    """As `filter_rows`, but a run matches a status if *any* of its tests did.

    A run's own status is a rollup, so filtering runs by `skipped` against that
    rollup would return nothing: the interesting question is which runs contain
    a skipped test.
    """
    rows = filter_rows(rows, q=q, status="all")
    if status == "all":
        return rows

    filtered = []
    for row in rows:
        by_status = row.get("by_status", {})
        failed_count = by_status.get("failed", 0) + by_status.get("error", 0)
        if status == "passed" and row.get("status") == "passed" and failed_count == 0:
            filtered.append(row)
        elif status in {"failed", "error", "skipped"} and (
            by_status.get(status, 0) > 0 or (status == "failed" and row.get("status") == "failed")
        ):
            filtered.append(row)
    return filtered


def dashboard(
    rows: Iterable[Any],
    *,
    q: str = "",
    status: str = "all",
    agent: str = "all",
    sort: str = "attention",
) -> dict:
    """The whole runs dashboard from one `list_runs` call.

    `rows` is fetched once by the caller and viewed once here. The stats band
    always describes the unfiltered set -- a filtered average score would move
    when the reader typed in the search box, which reads as data changing.
    """
    all_runs = [run_row(r) for r in rows]

    run_rows = all_runs
    if agent != "all":
        run_rows = [r for r in run_rows if r["agent_id"] == agent]
    run_rows = filter_run_rows(run_rows, q=q, status=status)

    if sort == "score":
        run_rows = sorted(run_rows, key=lambda r: (r["score_percent"], r["started"]))
    elif sort == "agent":
        run_rows = sorted(run_rows, key=lambda r: (r["agent_id"], r["started"]), reverse=True)
    else:
        run_rows = sorted(
            run_rows,
            key=lambda r: (
                not r["needs_attention"],
                -r["critical_failures"],
                r["status"] not in BAD_STATUSES,
                r["started"],
            ),
        )

    total_runs = len(all_runs)
    return {
        "runs": run_rows[:30],
        "all_runs": all_runs,
        "attention": [r for r in run_rows if r["needs_attention"]][:5],
        "agents": sorted({r["agent_id"] for r in all_runs}),
        "stats": {
            "total_runs": total_runs,
            "failed_runs": sum(1 for r in all_runs if r["status"] in BAD_STATUSES),
            "critical_failures": sum(r["critical_failures"] for r in all_runs),
            "avg_score": (
                int(sum(r["score_percent"] for r in all_runs) / total_runs) if total_runs else 0
            ),
        },
    }


def _library_row(pack_id: str | None, test_id: str, **extra: Any) -> dict:
    return {
        "pack_id": pack_id,
        "test_id": test_id,
        "id": test_id,
        "status": NEVER_RUN,
        "latest_status": NEVER_RUN,
        "latest_run_id": None,
        "latest_agent_id": None,
        "run_count": 0,
        "authored": False,
        **extra,
    }


def library(
    shipped: Iterable[tuple[str, Any]],
    authored: Iterable[dict],
    observed: Iterable[dict],
) -> list[dict]:
    """The test library: shipped packs, authored tests, and observed history.

    `shipped` is (pack_id, TestCase) pairs; `authored` is
    `Store.list_authored_tests`; `observed` is `Store.list_tests`.

    Precedence is deliberate. Shipped packs go in first so an authored test or
    run history for the same id overwrites them, not the other way round. Test
    ids are only unique within a pack, so duplicates stay separate rather than
    silently collapsing -- history is attached only when an id identifies
    exactly one known test, and otherwise lands on its own unpacked row.
    """
    rows: dict[tuple[str | None, str], dict] = {}
    for pack_id, test in shipped:
        rows[(pack_id, test.id)] = _library_row(
            pack_id,
            test.id,
            category=test.category.value,
            risk=test.risk.value,
        )
    for t in authored:
        extra = {k: v for k, v in t.items() if k not in ("pack_id", "test_id")}
        rows[(t["pack_id"], t["test_id"])] = _library_row(
            t["pack_id"], t["test_id"], **extra, authored=True
        )
    for t in observed:
        matches = [key for key in rows if key[1] == t["test_id"]]
        key = matches[0] if len(matches) == 1 else (None, t["test_id"])
        row = rows.setdefault(key, {"authored": False, "pack_id": None})
        row.update(t)
        row["id"] = t["test_id"]
        row["status"] = t["latest_status"]
    return list(rows.values())


def sort_library(rows: list[dict]) -> list[dict]:
    """Failures first, then by risk, so the reader lands on what is broken."""
    return sorted(
        rows,
        key=lambda t: (
            STATUS_RANK.get(t["latest_status"], _NEVER_RUN_RANK),
            _RISK_RANK.get(t["risk"], len(_RISK_RANK)),
            t["category"],
            t["test_id"],
        ),
    )


def result_rows(results: Iterable[Any]) -> list[dict]:
    """One run's results as table rows, failures first."""
    return [
        {
            "id": r.test_id,
            "test_id": r.test_id,
            "category": r.category.value,
            "risk": r.risk.value,
            "status": r.status.value,
            "latency_ms": r.latency_ms,
            "result": r,
        }
        for r in order_by_failure(results)
    ]


def detail(run: Any, *, q: str = "", status: str = "all", category: str = "all") -> dict:
    """One run's detail page: filtered rows, the category matrix, failures."""
    rows = filter_rows(result_rows(run.results), q=q, status=status)
    if category != "all":
        rows = [r for r in rows if r["category"] == category]

    matrix: dict[str, dict[str, str]] = {}
    for r in run.results:
        matrix.setdefault(r.category.value, {})[r.test_id] = r.status.value

    return {
        "results": [r["result"] for r in rows],
        "result_rows": rows,
        "matrix": matrix,
        "categories": sorted(matrix),
        "failures": [r for r in rows if r["status"] in BAD_STATUSES],
        "duration_ms": duration_ms(run.started_at, run.finished_at),
    }


def harness(run: Any, report: Any) -> dict:
    """The harness page: what was exercised, per category, in run order.

    Findings keep chronological order here rather than failure-first order: this
    page is read as a transcript of what the harness did, and reordering it
    would break the step numbering it shows.
    """
    memory_results = [r for r in run.results if r.category == Category.memory_context]

    skills = []
    for category_score in report.category_scores:
        category = category_score.category.value
        related = [r for r in run.results if r.category.value == category]
        skills.append(
            {
                "name": category.replace("_", " "),
                "category": category,
                "assertions": sorted({a.name for r in related for a in r.assertion_results}),
                "passed": category_score.passed,
                "total": category_score.total,
                "score": pct(category_score.score),
            }
        )

    findings = []
    for index, result in enumerate(
        sorted(run.results, key=lambda r: (r.started_at, r.test_id)), start=1
    ):
        details = [a.detail for a in failed_assertions(result) if a.detail]
        findings.append(
            {
                "step": index,
                "test_id": result.test_id,
                "category": result.category.value,
                "risk": result.risk.value,
                "status": result.status.value,
                "latency_ms": result.latency_ms,
                "started": str(result.started_at)[:19].replace("T", " "),
                "assertions": result.assertion_results,
                "summary": result.error or "; ".join(details) or "All assertions passed.",
            }
        )

    return {
        "summary": {
            "gate": "PASS" if report.gate_passed else "BLOCK",
            "overall_score": pct(report.overall_score),
            "pass_rate": pct(report.pass_rate),
            "critical_failures": report.critical_failures,
            "passed": report.passed,
            "total": report.total,
        },
        "context": {
            "agent": run.agent_name,
            "run_id": run.run_id,
            "started": short_date(run.started_at),
            "finished": short_date(run.finished_at),
            "categories": sorted({r.category.value for r in run.results}),
            "assertions": sorted({a.name for r in run.results for a in r.assertion_results}),
            "duration_ms": duration_ms(run.started_at, run.finished_at),
        },
        "memory": {
            "total": len(memory_results),
            "passed": sum(r.status == Status.passed for r in memory_results),
            "state_changes": sum(bool(r.sandbox_diff) for r in memory_results),
            "results": sorted(memory_results, key=lambda r: (r.started_at, r.test_id)),
        },
        "skills": skills,
        "findings": findings,
    }
