"""FastAPI + Jinja/HTMX-style dashboard over the Store. No JS build."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

import agentkit

# Eagerly import built-in domains so their sandboxes are registered before
# `build_sandbox` is ever called (see docs/notes/errors-and-improvements.md,
# "feat/runner" section, for why this matters).
import agentkit.domains.email.sandbox  # noqa: F401
import agentkit.domains.treasury.sandbox  # noqa: F401
from agentkit.core.assertions import REGISTRY as ASSERTION_REGISTRY
from agentkit.core.config import load_target
from agentkit.core.loader import discover
from agentkit.core.regressions import compare
from agentkit.core.runner import run as run_tests
from agentkit.core.schema import Category, Risk, Status, TestCase
from agentkit.core.scoring import score
from agentkit.core.store import Store
from agentkit.web.auth import Principal, auth_enabled, current_principal

BASE_DIR = Path(__file__).parent
PACKAGE_DIR = Path(agentkit.__file__).resolve().parent
# Roots the web run route is allowed to load targets/packs from. Callers pass
# paths relative to these; anything resolving outside is rejected, so the route
# can never be coaxed into loading arbitrary Python callables. See
# docs/archive/plans/MERGED-PLAN.md §0a; registered IDs replace this in Phase 1.
_ALLOWED_ROOTS = (PACKAGE_DIR / "config", PACKAGE_DIR / "packs")


def _resolve_within_allowed(value: str) -> Path:
    candidate = Path(value).resolve()
    for root in _ALLOWED_ROOTS:
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.exists():
            return candidate
    raise HTTPException(
        status_code=400,
        detail="target/packs must resolve to a file under config/ or packs/",
    )


_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=select_autoescape(["html"]),
)

_STATUS_RANK = {"failed": 0, "error": 0, "passed": 1, "skipped": 2}
_BAD_STATUSES = {"failed", "error"}
_STATUS_LABELS = {
    "all": "All statuses",
    "failed": "Failed",
    "error": "Error",
    "passed": "Passed",
    "skipped": "Skipped",
}

# Swagger/ReDoc/openapi.json are off: they cannot carry a principal, so they
# would be the only unauthenticated routes on a partner-facing deployment, and
# they publish the whole route surface for free.
app = FastAPI(title="agentkit", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def get_db_path() -> str:
    return os.environ.get("AGENTKIT_DB", "database/agentkit.db")


def get_store() -> Store:
    return Store(get_db_path())


def _render(template_name: str, status_code: int = 200, **context) -> HTMLResponse:
    context.setdefault("active", "dashboard")
    context.setdefault("status_labels", _STATUS_LABELS)
    template = _env.get_template(template_name)
    return HTMLResponse(template.render(**context), status_code=status_code)


def _pct(value: float | int | None) -> int:
    if value is None:
        return 0
    return int(float(value) * 100)


def _short_date(value) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value or "")
    return text[:16].replace("T", " ")


def _duration_ms(started, finished) -> float | None:
    try:
        return max(0.0, (finished - started).total_seconds() * 1000)
    except TypeError:
        return None


def _summary_total(summary: dict) -> int:
    return sum(summary.get("by_status", {}).values())


def _run_view(row) -> dict:
    score = row.score
    by_status = row.summary.get("by_status", {})
    total = _summary_total(row.summary)
    failed = by_status.get("failed", 0) + by_status.get("error", 0)
    return {
        "row": row,
        "id": row.id,
        "short_id": row.id[:8],
        "agent_id": row.agent_id,
        "started": _short_date(row.started_at),
        # CLI runs have no principal; show that rather than inventing one.
        "launched_by": row.created_by_email or row.created_by or "CLI",
        "finished": _short_date(row.finished_at),
        "status": row.status,
        "by_status": by_status,
        "score_percent": _pct(score.get("overall_score", 0)),
        "pass_percent": _pct(score.get("pass_rate", 0)),
        "critical_failures": score.get("critical_failures", 0),
        "total": total,
        "failed": failed,
        "passed": by_status.get("passed", 0),
        "skipped": by_status.get("skipped", 0),
        "needs_attention": row.status in _BAD_STATUSES
        or score.get("critical_failures", 0) > 0,
    }


def _filter_rows(rows: list[dict], q: str = "", status: str = "all") -> list[dict]:
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


def _filter_run_rows(rows: list[dict], q: str = "", status: str = "all") -> list[dict]:
    rows = _filter_rows(rows, q=q, status="all")
    if status == "all":
        return rows

    filtered = []
    for row in rows:
        by_status = row.get("by_status", {})
        failed_count = by_status.get("failed", 0) + by_status.get("error", 0)
        if status == "passed" and row.get("status") == "passed" and failed_count == 0:
            filtered.append(row)
        elif status in {"failed", "error", "skipped"} and by_status.get(status, 0) > 0:
            filtered.append(row)
        elif status == "failed" and row.get("status") == "failed":
            filtered.append(row)
    return filtered


def _runs_page(request: Request, org_id: str) -> HTMLResponse:
    store = get_store()
    q = request.query_params.get("q", "")
    status = request.query_params.get("status", "all")
    agent = request.query_params.get("agent", "all")
    sort = request.query_params.get("sort", "attention")

    run_rows = [_run_view(r) for r in store.list_runs(org_id, limit=100)]
    if agent != "all":
        run_rows = [r for r in run_rows if r["agent_id"] == agent]
    run_rows = _filter_run_rows(run_rows, q=q, status=status)

    if sort == "score":
        run_rows.sort(key=lambda r: (r["score_percent"], r["started"]))
    elif sort == "agent":
        run_rows.sort(key=lambda r: (r["agent_id"], r["started"]), reverse=True)
    else:
        run_rows.sort(
            key=lambda r: (
                not r["needs_attention"],
                -r["critical_failures"],
                r["status"] not in _BAD_STATUSES,
                r["started"],
            )
        )

    all_runs = [_run_view(r) for r in store.list_runs(org_id, limit=100)]
    total_runs = len(all_runs)
    failed_runs = sum(1 for r in all_runs if r["status"] in _BAD_STATUSES)
    critical_failures = sum(r["critical_failures"] for r in all_runs)
    avg_score = int(
        sum(r["score_percent"] for r in all_runs) / total_runs
    ) if total_runs else 0
    agents = sorted({r["agent_id"] for r in all_runs})
    attention = [r for r in run_rows if r["needs_attention"]][:5]

    return _render(
        "dashboard.html",
        runs=run_rows[:30],
        all_runs=all_runs,
        attention=attention,
        filters={"q": q, "status": status, "agent": agent, "sort": sort},
        agents=agents,
        stats={
            "total_runs": total_runs,
            "failed_runs": failed_runs,
            "critical_failures": critical_failures,
            "avg_score": avg_score,
        },
        active="runs",
    )


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    return _runs_page(request, principal.org_id)


@app.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    return _runs_page(request, principal.org_id)


@app.get("/agents", response_class=HTMLResponse)
def agents_page(principal: Principal = Depends(current_principal)) -> HTMLResponse:
    store = get_store()
    agents = store.list_agents(principal.org_id)
    rows = []
    for a in agents:
        latest = store.list_runs(principal.org_id, a.id, limit=1)
        rows.append(
            {
                "agent": a,
                "latest": latest[0] if latest else None,
                "run_count": store.run_count(principal.org_id, a.id),
            }
        )
    return _render("agents.html", agent_rows=rows, active="agents")


@app.get("/agents/connect", response_class=HTMLResponse)
def connect_agent_page(principal: Principal = Depends(current_principal)) -> HTMLResponse:
    targets = sorted(
        p.relative_to(PACKAGE_DIR).as_posix()
        for p in (PACKAGE_DIR / "config").glob("*.yaml")
    )
    pack_roots = sorted(
        p.relative_to(PACKAGE_DIR).as_posix()
        for p in (PACKAGE_DIR / "packs").iterdir()
        if p.is_dir()
    )
    return _render(
        "agent_connect.html",
        targets=targets,
        pack_roots=pack_roots,
        active="agents",
    )


# :path so URL-shaped agent ids (e.g. "http://127.0.0.1:9911/") keep their slashes.
@app.get("/agents/{agent_id:path}", response_class=HTMLResponse)
def agent_detail(agent_id: str, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    store = get_store()
    runs = store.list_runs(principal.org_id, agent_id)
    matrix = store.pass_fail_matrix(principal.org_id, agent_id)
    latest_run_id = runs[0].id if runs else None
    run_views = [_run_view(r) for r in runs]
    failures = [r for r in run_views if r["needs_attention"]]
    return _render(
        "agent_detail.html",
        agent_id=agent_id,
        runs=runs,
        run_views=run_views,
        failures=failures,
        matrix=matrix,
        latest_run_id=latest_run_id,
        active="agents",
    )


def get_packs_dir() -> Path:
    return Path(os.environ.get("AGENTKIT_PACKS", str(PACKAGE_DIR / "packs")))


@app.get("/tests", response_class=HTMLResponse)
def tests_page(request: Request, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    store = get_store()
    q = request.query_params.get("q", "")
    status = request.query_params.get("status", "all")
    risk = request.query_params.get("risk", "all")
    category = request.query_params.get("category", "all")
    tests = store.list_tests(principal.org_id)
    rows = []
    for t in tests:
        row = dict(t)
        row["id"] = row["test_id"]
        row["status"] = row["latest_status"]
        rows.append(row)
    rows = _filter_rows(rows, q=q, status=status)
    if risk != "all":
        rows = [r for r in rows if r["risk"] == risk]
    if category != "all":
        rows = [r for r in rows if r["category"] == category]
    rows.sort(
        key=lambda t: (
            _STATUS_RANK.get(t["latest_status"], 3),
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(t["risk"], 4),
            t["category"],
            t["test_id"],
        )
    )
    return _render(
        "tests.html",
        tests=rows,
        filters={"q": q, "status": status, "risk": risk, "category": category},
        categories=[c.value for c in Category],
        risks=[r.value for r in Risk],
        active="tests",
    )


@app.get("/tests/new", response_class=HTMLResponse)
def new_test_form(
    principal: Principal = Depends(current_principal),
) -> HTMLResponse:
    return _test_form()


# Separate from the route above so `create_test` can re-render the form with an
# error without going through dependency resolution.
def _test_form(error: str | None = None, values: dict | None = None) -> HTMLResponse:
    return _render(
        "test_new.html",
        categories=[c.value for c in Category],
        risks=[r.value for r in Risk],
        assertions=sorted(ASSERTION_REGISTRY),
        error=error,
        values=values or {},
        active="tests",
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(principal: Principal = Depends(current_principal)) -> HTMLResponse:
    auth_state = (
        f"OIDC ({os.environ['AGENTKIT_OIDC_ISSUER']})"
        if auth_enabled()
        else "Unauthenticated (single-tenant dev mode, loopback only)"
    )
    return _render(
        "settings.html",
        settings={
            "db_path": get_db_path(),
            "package_dir": str(PACKAGE_DIR),
            "config_dir": str(PACKAGE_DIR / "config"),
            "packs_dir": str(get_packs_dir()),
            "auth_state": auth_state,
        },
        active="settings",
    )


@app.post("/tests")
def create_test(
    test_id: str = Form(...),
    category: str = Form(...),
    risk: str = Form(...),
    input: str = Form(...),
    assertion_name: str = Form(...),
    assertion_args: str = Form(""),
    principal: Principal = Depends(current_principal),
) -> Response:
    values = {
        "test_id": test_id,
        "category": category,
        "risk": risk,
        "input": input,
        "assertion_name": assertion_name,
        "assertion_args": assertion_args,
    }

    def _fail(message: str) -> HTMLResponse:
        return _test_form(error=message, values=values)

    args: dict = {}
    if assertion_args.strip():
        try:
            args = yaml.safe_load(assertion_args)
        except yaml.YAMLError as exc:
            return _fail(f"Assertion args are not valid YAML: {exc}")
        if not isinstance(args, dict):
            return _fail("Assertion args must be a YAML mapping, e.g. {values: [\"sk-\"]}")

    raw = {
        "id": test_id,
        "category": category,
        "risk": risk,
        "input": input,
        "assertions": [{"name": assertion_name, "args": args}],
    }
    try:
        test_case = TestCase.model_validate(raw)
    except ValidationError as exc:
        return _fail(f"Invalid test: {exc.errors()[0]['msg']}")

    if assertion_name not in ASSERTION_REGISTRY:
        return _fail(f"Unknown assertion '{assertion_name}'")

    dest = get_packs_dir() / "user" / f"{test_id}.yaml"
    if dest.exists():
        return _fail(f"A test file already exists at {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = test_case.model_dump(mode="json", exclude_defaults=True)
    dest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return RedirectResponse(url="/tests", status_code=303)


def _load_run_or_404(org_id: str, run_id: str):
    store = get_store()
    try:
        return store.get_run(org_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found") from exc


def _harness_view(run, report) -> dict:
    categories = sorted({r.category.value for r in run.results})
    assertions = sorted({a.name for r in run.results for a in r.assertion_results})
    memory_results = [
        r for r in run.results if r.category == Category.memory_context
    ]
    skills = []
    for category_score in report.category_scores:
        category = category_score.category.value
        related = [r for r in run.results if r.category.value == category]
        skills.append(
            {
                "name": category.replace("_", " "),
                "category": category,
                "assertions": sorted(
                    {a.name for r in related for a in r.assertion_results}
                ),
                "passed": category_score.passed,
                "total": category_score.total,
                "score": _pct(category_score.score),
            }
        )

    findings = []
    for index, result in enumerate(
        sorted(run.results, key=lambda r: (r.started_at, r.test_id)), start=1
    ):
        failed_assertions = [a for a in result.assertion_results if not a.passed]
        details = [a.detail for a in failed_assertions if a.detail]
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
                "summary": result.error
                or "; ".join(details)
                or "All assertions passed.",
            }
        )

    return {
        "summary": {
            "gate": "PASS" if report.gate_passed else "BLOCK",
            "overall_score": _pct(report.overall_score),
            "pass_rate": _pct(report.pass_rate),
            "critical_failures": report.critical_failures,
            "passed": report.passed,
            "total": report.total,
        },
        "context": {
            "agent": run.agent_name,
            "run_id": run.run_id,
            "started": _short_date(run.started_at),
            "finished": _short_date(run.finished_at),
            "categories": categories,
            "assertions": assertions,
            "duration_ms": _duration_ms(run.started_at, run.finished_at),
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


@app.get("/harness", response_class=HTMLResponse)
def latest_harness(principal: Principal = Depends(current_principal)) -> Response:
    latest_runs = get_store().list_runs(principal.org_id, limit=1)
    if not latest_runs:
        return _render("harness_empty.html", active="harness")
    return RedirectResponse(
        url=f"/runs/{latest_runs[0].id}/harness", status_code=302
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: str, request: Request, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    rr, report = _load_run_or_404(principal.org_id, run_id)
    q = request.query_params.get("q", "")
    status = request.query_params.get("status", "all")
    category = request.query_params.get("category", "all")

    results = sorted(
        rr.results, key=lambda r: (_STATUS_RANK.get(r.status.value, 1), r.test_id)
    )
    result_rows = []
    for r in results:
        result_rows.append(
            {
                "id": r.test_id,
                "test_id": r.test_id,
                "category": r.category.value,
                "risk": r.risk.value,
                "status": r.status.value,
                "latency_ms": r.latency_ms,
                "result": r,
            }
        )
    result_rows = _filter_rows(result_rows, q=q, status=status)
    if category != "all":
        result_rows = [r for r in result_rows if r["category"] == category]

    matrix: dict[str, dict[str, str]] = {}
    for r in rr.results:
        matrix.setdefault(r.category.value, {})[r.test_id] = r.status.value
    failures = [r for r in result_rows if r["status"] in _BAD_STATUSES]
    duration = _duration_ms(rr.started_at, rr.finished_at)

    return _render(
        "run_detail.html",
        run=rr,
        report=report,
        results=[r["result"] for r in result_rows],
        result_rows=result_rows,
        matrix=matrix,
        failures=failures,
        duration_ms=duration,
        filters={"q": q, "status": status, "category": category},
        categories=sorted(matrix),
    )


@app.get("/runs/{run_id}/harness", response_class=HTMLResponse)
def run_harness(run_id: str, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    run, report = _load_run_or_404(principal.org_id, run_id)
    return _render(
        "run_harness.html",
        run=run,
        report=report,
        harness=_harness_view(run, report),
        active="harness",
    )


@app.get("/runs/{run_id}/tests/{test_id}", response_class=HTMLResponse)
def test_detail(run_id: str, test_id: str, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    rr, _report = _load_run_or_404(principal.org_id, run_id)
    result = next((r for r in rr.results if r.test_id == test_id), None)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"test '{test_id}' not found in run '{run_id}'"
        )
    ordered = sorted(
        rr.results, key=lambda r: (_STATUS_RANK.get(r.status.value, 1), r.test_id)
    )
    idx = next(i for i, r in enumerate(ordered) if r.test_id == test_id)
    passed_assertions = sum(1 for a in result.assertion_results if a.passed)
    artifact_states = [
        {
            "name": "Trace",
            "state": "Unavailable",
            "detail": "The current result model does not persist Playwright-style traces.",
        },
        {
            "name": "Screenshots / video",
            "state": "Unavailable",
            "detail": "Artifact URLs are not captured for this run yet.",
        },
        {
            "name": "Sandbox diff",
            "state": "Available" if result.sandbox_diff else "Empty",
            "detail": "Captured state changes around the test execution.",
        },
    ]
    return _render(
        "test_detail.html",
        run=rr,
        result=result,
        previous_result=ordered[idx - 1] if idx > 0 else None,
        next_result=ordered[idx + 1] if idx + 1 < len(ordered) else None,
        passed_assertions=passed_assertions,
        failed_assertions=len(result.assertion_results) - passed_assertions,
        artifact_states=artifact_states,
    )


@app.get("/runs/{run_id}/status", response_class=HTMLResponse)
def run_status(run_id: str, request: Request, principal: Principal = Depends(current_principal)) -> Response:
    rr, report = _load_run_or_404(principal.org_id, run_id)
    if "application/json" in request.headers.get("accept", "").lower():
        if rr.finished_at:
            message = (
                f"Finished at {rr.finished_at} - "
                f"Gate: {'PASS' if report.gate_passed else 'BLOCK'}"
            )
            running = False
        else:
            message = "Running..."
            running = True
        return JSONResponse(
            {
                "run_id": rr.run_id,
                "message": message,
                "running": running,
            }
        )
    return _render("_status_fragment.html", run=rr, report=report)


def _safe_path(p: str) -> Path:
    resolved = Path(p).resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise HTTPException(status_code=400, detail="path escapes project root")
    return resolved


@app.post("/runs")
def run_again(target: str, packs: str, request: Request) -> RedirectResponse:
    principal = current_principal(request)
    cfg = load_target(str(_resolve_within_allowed(target)))
    tests = discover(str(_resolve_within_allowed(packs)))
    rr = run_tests(cfg, tests)
    report = score(rr)
    store = get_store()
    store.save_run(
        principal.org_id,
        cfg,
        rr,
        report,
        created_by=principal.subject,
        created_by_email=principal.email,
    )
    return RedirectResponse(url=f"/runs/{rr.run_id}", status_code=303)


@app.get("/compare", response_class=HTMLResponse)
def compare_runs(a: str, b: str, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    before, before_score = _load_run_or_404(principal.org_id, a)
    after, after_score = _load_run_or_404(principal.org_id, b)
    diff = compare(before, after, before_score, after_score)
    return _render(
        "compare.html",
        run_a=before,
        run_b=after,
        diff=diff,
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> Response:
    if "application/json" in request.headers.get("accept", "").lower():
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return _render(
        "error.html",
        status_code=exc.status_code,
        display_status=exc.status_code,
        detail=exc.detail,
        active="dashboard",
    )
