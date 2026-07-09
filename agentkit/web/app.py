"""FastAPI + Jinja/HTMX-style dashboard over the Store. No JS build."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Eagerly import built-in domains so their sandboxes are registered before
# `build_sandbox` is ever called (see docs/notes/errors-and-improvements.md,
# "feat/runner" section, for why this matters).
import agentkit.domains.email.sandbox  # noqa: F401
import agentkit.domains.treasury.sandbox  # noqa: F401
from agentkit.core.config import load_target
from agentkit.core.loader import discover
from agentkit.core.runner import run as run_tests
from agentkit.core.scoring import score
from agentkit.core.store import Store

BASE_DIR = Path(__file__).parent

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
        rows.append({"agent": a, "latest": latest[0] if latest else None})
    return _render("agents.html", agent_rows=rows)


@app.get("/agents/{agent_id}", response_class=HTMLResponse)
def agent_detail(agent_id: str) -> HTMLResponse:
    store = get_store()
    runs = store.list_runs(agent_id)
    matrix = store.pass_fail_matrix(agent_id)
    return _render("agent_detail.html", agent_id=agent_id, runs=runs, matrix=matrix)


def _load_run_or_404(run_id: str):
    store = get_store()
    try:
        return store.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: str) -> HTMLResponse:
    rr, report = _load_run_or_404(run_id)

    results = sorted(
        rr.results, key=lambda r: (_STATUS_RANK.get(r.status.value, 1), r.test_id)
    )
    matrix: dict[str, dict[str, str]] = {}
    for r in rr.results:
        matrix.setdefault(r.category.value, {})[r.test_id] = r.status.value

    return _render("run_detail.html", run=rr, report=report, results=results, matrix=matrix)


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
def run_status(run_id: str) -> HTMLResponse:
    rr, report = _load_run_or_404(run_id)
    return _render("_status_fragment.html", run=rr, report=report)


@app.post("/runs")
def run_again(target: str, packs: str) -> RedirectResponse:
    cfg = load_target(target)
    tests = discover(packs)
    rr = run_tests(cfg, tests)
    report = score(rr)
    store = get_store()
    store.save_run(cfg, rr, report)
    return RedirectResponse(url=f"/runs/{rr.run_id}", status_code=303)
