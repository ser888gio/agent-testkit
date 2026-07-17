"""FastAPI + Jinja/HTMX-style dashboard over the Store. No JS build."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import yaml
from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

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
from agentkit.core.schema import Category, Risk, TestCase
from agentkit.core.scoring import score
from agentkit.core.store import Store

BASE_DIR = Path(__file__).parent
# Roots the web run route is allowed to load targets/packs from. Callers pass
# paths relative to these; anything resolving outside is rejected, so the route
# can never be coaxed into loading arbitrary Python callables. See
# MERGED-PLAN.md §0a; registered IDs replace this in Phase 1.
_PACKAGE_DIR = BASE_DIR.parent
_ALLOWED_ROOTS = (_PACKAGE_DIR / "config", _PACKAGE_DIR / "packs")

# Loopback access token: generated per process, required for state-changing
# routes. Reject public binding unless explicitly overridden for local dev.
_ACCESS_TOKEN = os.environ.get("AGENTKIT_WEB_TOKEN") or secrets.token_urlsafe(16)


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


def _require_token(request: Request) -> None:
    token = request.query_params.get("token") or request.headers.get(
        "x-agentkit-token", ""
    )
    if not secrets.compare_digest(token, _ACCESS_TOKEN):
        raise HTTPException(status_code=403, detail="missing or invalid access token")

_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=select_autoescape(["html"]),
)

_STATUS_RANK = {"failed": 0, "error": 0, "passed": 1, "skipped": 2}

app = FastAPI(title="agentkit")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def get_db_path() -> str:
    return os.environ.get("AGENTKIT_DB", "agentkit.db")


def get_store() -> Store:
    return Store(get_db_path())


def _render(template_name: str, **context) -> HTMLResponse:
    template = _env.get_template(template_name)
    return HTMLResponse(template.render(**context))


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    store = get_store()
    runs = store.list_runs(limit=20)
    return _render("dashboard.html", runs=runs)


@app.get("/agents", response_class=HTMLResponse)
def agents_page() -> HTMLResponse:
    store = get_store()
    agents = store.list_agents()
    rows = []
    for a in agents:
        latest = store.list_runs(a.id, limit=1)
        rows.append(
            {
                "agent": a,
                "latest": latest[0] if latest else None,
                "run_count": store.run_count(a.id),
            }
        )
    return _render("agents.html", agent_rows=rows)


@app.get("/agents/{agent_id}", response_class=HTMLResponse)
def agent_detail(agent_id: str) -> HTMLResponse:
    store = get_store()
    runs = store.list_runs(agent_id)
    matrix = store.pass_fail_matrix(agent_id)
    latest_run_id = runs[0].id if runs else None
    return _render(
        "agent_detail.html",
        agent_id=agent_id,
        runs=runs,
        matrix=matrix,
        latest_run_id=latest_run_id,
    )


def get_packs_dir() -> Path:
    return Path(os.environ.get("AGENTKIT_PACKS", "agentkit/packs"))


@app.get("/tests", response_class=HTMLResponse)
def tests_page() -> HTMLResponse:
    store = get_store()
    tests = store.list_tests()
    return _render("tests.html", tests=tests)


@app.get("/tests/new", response_class=HTMLResponse)
def new_test_form(error: str | None = None, values: dict | None = None) -> HTMLResponse:
    return _render(
        "test_new.html",
        categories=[c.value for c in Category],
        risks=[r.value for r in Risk],
        assertions=sorted(ASSERTION_REGISTRY),
        error=error,
        values=values or {},
    )


@app.post("/tests")
def create_test(
    test_id: str = Form(...),
    category: str = Form(...),
    risk: str = Form(...),
    input: str = Form(...),
    assertion_name: str = Form(...),
    assertion_args: str = Form(""),
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
        return new_test_form(error=message, values=values)

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


def _load_run_or_404(run_id: str):
    store = get_store()
    try:
        return store.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found") from exc


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: str) -> HTMLResponse:
    rr, report = _load_run_or_404(run_id)

    results = sorted(
        rr.results, key=lambda r: (_STATUS_RANK.get(r.status.value, 1), r.test_id)
    )
    matrix: dict[str, dict[str, str]] = {}
    for r in rr.results:
        matrix.setdefault(r.category.value, {})[r.test_id] = r.status.value

    return _render(
        "run_detail.html", run=rr, report=report, results=results, matrix=matrix
    )


@app.get("/runs/{run_id}/tests/{test_id}", response_class=HTMLResponse)
def test_detail(run_id: str, test_id: str) -> HTMLResponse:
    rr, _report = _load_run_or_404(run_id)
    result = next((r for r in rr.results if r.test_id == test_id), None)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"test '{test_id}' not found in run '{run_id}'"
        )
    return _render("test_detail.html", run=rr, result=result)


@app.get("/runs/{run_id}/status", response_class=HTMLResponse)
def run_status(run_id: str, request: Request) -> Response:
    rr, report = _load_run_or_404(run_id)
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
    _require_token(request)
    cfg = load_target(str(_resolve_within_allowed(target)))
    tests = discover(str(_resolve_within_allowed(packs)))
    rr = run_tests(cfg, tests)
    report = score(rr)
    store = get_store()
    store.save_run(cfg, rr, report)
    return RedirectResponse(url=f"/runs/{rr.run_id}", status_code=303)


@app.get("/compare", response_class=HTMLResponse)
def compare_runs(a: str, b: str) -> HTMLResponse:
    before, before_score = _load_run_or_404(a)
    after, after_score = _load_run_or_404(b)
    diff = compare(before, after, before_score, after_score)
    return _render(
        "compare.html",
        run_a=before,
        run_b=after,
        diff=diff,
    )
