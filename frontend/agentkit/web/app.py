"""FastAPI + Jinja/HTMX-style dashboard over the Store. No JS build."""

from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from urllib.parse import quote, urlsplit

# Eagerly import built-in domains so their sandboxes are registered before
# `build_sandbox` is ever called (see docs/notes/errors-and-improvements.md,
# "feat/runner" section, for why this matters).
import agentkit.domains.email.sandbox  # noqa: F401
import agentkit.domains.treasury.sandbox  # noqa: F401
import yaml
from agentkit.core.assertions import REGISTRY as ASSERTION_REGISTRY
from agentkit.core.loader import LoaderError, discover
from agentkit.core.redaction import builtin_pattern_names
from agentkit.core.regressions import compare
from agentkit.core.schema import Category, Risk, Status, TestCase
from agentkit.core.store import Store
from agentkit.web.auth import (
    LOGIN_STATE_COOKIE,
    SESSION_COOKIE,
    Principal,
    auth_enabled,
    begin_browser_login,
    complete_browser_login,
    cookie_secure,
    current_principal,
    end_browser_session,
    require_admin,
    reset_auth_state,
)
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

import agentkit

BASE_DIR = Path(__file__).parent
PACKAGE_DIR = Path(agentkit.__file__).resolve().parent
# Roots the web run route is allowed to load targets/packs from. Callers pass
# paths relative to these; anything resolving outside is rejected, so the route
# can never be coaxed into loading arbitrary Python callables. See
# docs/archive/plans/MERGED-PLAN.md §0a; registered IDs replace this in Phase 1.
_ALLOWED_ROOTS = (PACKAGE_DIR / "config", PACKAGE_DIR / "packs")

# Pack that tenant-authored tests land in, one per org.
USER_PACK_ID = "user"

_ENV_REFS_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


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

def get_db_path() -> str:
    return os.environ.get("AGENTKIT_DB", "database/agentkit.db")


# One long-lived Store per process instead of one connection per handler call.
# Store hands each thread its own connection and reuses it, so the open-handle
# count tracks the (bounded) threadpool rather than the request count.
_store: Store | None = None
_store_path: str | None = None


def get_store() -> Store:
    global _store, _store_path
    path = get_db_path()
    if _store is None or _store_path != path:
        # The path only changes under tests, which point AGENTKIT_DB at a tmp
        # dir per case; closing the old one keeps them from accumulating.
        if _store is not None:
            _store.close()
        _store = Store(path)
        _store_path = path
    return _store


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _store, _store_path
    # Validate authentication before accepting traffic. An unset mode is a
    # deployment error; loopback development must opt in explicitly.
    auth_enabled()
    get_store()
    try:
        yield
    finally:
        reset_auth_state()
        if _store is not None:
            _store.close()
        _store = None
        _store_path = None


# Swagger/ReDoc/openapi.json are off: they cannot carry a principal, so they
# would be the only unauthenticated routes on a partner-facing deployment, and
# they publish the whole route surface for free.
app = FastAPI(
    title="agentkit",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _render(template_name: str, status_code: int = 200, **context) -> HTMLResponse:
    context.setdefault("active", "dashboard")
    context.setdefault("status_labels", _STATUS_LABELS)
    context.setdefault("oidc_enabled", auth_enabled())
    template = _env.get_template(template_name)
    return HTMLResponse(template.render(**context), status_code=status_code)


@app.get("/login", include_in_schema=False)
def login(next: str | None = None) -> RedirectResponse:  # noqa: A002
    destination, state = begin_browser_login(next)
    response = RedirectResponse(destination, status_code=302)
    if state:
        response.set_cookie(
            LOGIN_STATE_COOKIE,
            state,
            max_age=300,
            httponly=True,
            secure=cookie_secure(),
            samesite="lax",
        )
    return response


@app.get("/auth/callback", include_in_schema=False)
def auth_callback(code: str, state: str, request: Request) -> RedirectResponse:
    session_id, _principal, destination = complete_browser_login(
        code,
        state,
        request.cookies.get(LOGIN_STATE_COOKIE, ""),
    )
    response = RedirectResponse(destination, status_code=303)
    response.delete_cookie(LOGIN_STATE_COOKIE)
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=3600,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
    )
    return response


@app.get("/logout", include_in_schema=False)
def logout(request: Request) -> RedirectResponse:
    destination = end_browser_session(request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse(destination, status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


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


def _is_pack_dir(p: Path) -> bool:
    """Tooling and cache directories live beside the packs; they are not packs."""
    return p.is_dir() and not p.name.startswith((".", "__"))


@app.get("/agents/connect", response_class=HTMLResponse)
def connect_agent_page(principal: Principal = Depends(current_principal)) -> HTMLResponse:
    # Relative to the package's parent (the project root the server runs from):
    # _resolve_within_allowed resolves these against CWD, so "agentkit/config/x"
    # is the form that round-trips; "config/x" would 400 on submit.
    root = PACKAGE_DIR.parent
    targets = sorted(
        p.relative_to(root).as_posix()
        for p in (PACKAGE_DIR / "config").glob("*.yaml")
    )
    pack_roots = sorted(
        p.relative_to(root).as_posix()
        for p in (PACKAGE_DIR / "packs").iterdir()
        if _is_pack_dir(p)
    )
    # Default to whatever this org last launched -- derived, not a stored
    # preference. Jobs record the target's yaml `id` and the pack directory
    # name (_import_first_party), so map the path options back the same way.
    last_jobs = get_store().list_jobs(principal.org_id, limit=1)
    default_target = default_pack = None
    if last_jobs:
        for rel in targets:
            try:
                raw = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if isinstance(raw, dict) and str(raw.get("id")) == last_jobs[0].target_id:
                default_target = rel
                break
        default_pack = next(
            (rel for rel in pack_roots if Path(rel).name == last_jobs[0].pack_id),
            None,
        )
    return _render(
        "agent_connect.html",
        targets=targets,
        pack_roots=pack_roots,
        default_target=default_target,
        default_pack=default_pack,
        csrf_token=principal.csrf_token,
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


def _test_rows(store: Store, org_id: str) -> list[dict]:
    """Authored tests plus tests observed in this org's runs.

    An authored test that has never run still belongs on the page; run history
    supplies its latest status when a test id identifies exactly one authored
    test. Test ids are only unique within a pack, so duplicate ids must remain
    separate instead of silently overwriting one another.

    Shipped packs come first so an authored test or run history for the same id
    overwrites them, not the other way round.
    """
    rows: dict[tuple[str | None, str], dict] = {}
    # AGENTKIT_PACKS may point somewhere that does not exist yet; an absent
    # packs directory means no shipped tests, not a 500.
    packs_root = get_packs_dir()
    shipped = (
        sorted(p for p in packs_root.iterdir() if _is_pack_dir(p))
        if packs_root.is_dir()
        else []
    )
    for pack_dir in shipped:
        for test in discover(str(pack_dir)):
            # discover() also loads Python test modules, which carry no metadata
            # to render; only YAML-backed TestCases belong in the library table.
            if not isinstance(test, TestCase):
                continue
            rows[(pack_dir.name, test.id)] = {
                "pack_id": pack_dir.name,
                "test_id": test.id,
                "id": test.id,
                "category": test.category.value,
                "risk": test.risk.value,
                "status": "never run",
                "latest_status": "never run",
                "latest_run_id": None,
                "latest_agent_id": None,
                "run_count": 0,
                "authored": False,
            }
    for t in store.list_authored_tests(org_id):
        rows[(t["pack_id"], t["test_id"])] = {
            **t,
            "id": t["test_id"],
            "status": "never run",
            "latest_status": "never run",
            "latest_run_id": None,
            "latest_agent_id": None,
            "run_count": 0,
            "authored": True,
        }
    for t in store.list_tests(org_id):
        matches = [key for key in rows if key[1] == t["test_id"]]
        key = matches[0] if len(matches) == 1 else (None, t["test_id"])
        row = rows.setdefault(key, {"authored": False, "pack_id": None})
        row.update(t)
        row["id"] = t["test_id"]
        row["status"] = t["latest_status"]
    return list(rows.values())


@app.get("/tests", response_class=HTMLResponse)
def tests_page(request: Request, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    store = get_store()
    q = request.query_params.get("q", "")
    status = request.query_params.get("status", "all")
    risk = request.query_params.get("risk", "all")
    category = request.query_params.get("category", "all")
    rows = _test_rows(store, principal.org_id)
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
    return _test_form(csrf_token=principal.csrf_token)


# Separate from the route above so `create_test` can re-render the form with an
# error without going through dependency resolution.
def _test_form(
    error: str | None = None,
    values: dict | None = None,
    csrf_token: str = "",
) -> HTMLResponse:
    return _render(
        "test_new.html",
        categories=[c.value for c in Category],
        risks=[r.value for r in Risk],
        assertions=sorted(ASSERTION_REGISTRY),
        error=error,
        values=values or {},
        csrf_token=csrf_token,
        active="tests",
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(principal: Principal = Depends(current_principal)) -> HTMLResponse:
    auth_state = (
        f"OIDC ({os.environ['AGENTKIT_OIDC_ISSUER']})"
        if auth_enabled()
        else "Local development principal (single-tenant, loopback only)"
    )
    return _render(
        "settings.html",
        settings={
            "db_path": get_db_path(),
            "package_dir": str(PACKAGE_DIR),
            "config_dir": str(PACKAGE_DIR / "config"),
            "packs_dir": str(get_packs_dir()),
            "auth_state": auth_state,
            "redaction_patterns": builtin_pattern_names(),
            "egress_allow_local": os.environ.get("AGENTKIT_EGRESS_ALLOW_LOCAL") == "1",
        },
        principal=principal,
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
    principal: Principal = Depends(require_admin),
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
        return _test_form(
            error=message,
            values=values,
            csrf_token=principal.csrf_token,
        )

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

    # Authored tests are DB rows scoped to the caller's org, never files: the
    # packs directory is shared, and every org's discover() walks all of it.
    store = get_store()
    store.ensure_pack(principal.org_id, USER_PACK_ID, "User-authored tests")
    try:
        store.save_pack_test(
            principal.org_id,
            USER_PACK_ID,
            test_case.model_dump(mode="json", exclude_defaults=True),
            created_by=principal.subject,
            created_by_email=principal.email,
        )
    except LoaderError as exc:
        return _fail(str(exc))
    return RedirectResponse(url="/tests", status_code=303)


def get_artifacts_dir() -> Path:
    return Path(os.environ.get("AGENTKIT_ARTIFACTS_DIR", "database/artifacts"))


@app.get("/artifacts/{artifact_id}")
def download_artifact(
    artifact_id: str, principal: Principal = Depends(current_principal)
) -> Response:
    """The only permitted way to serve a blob.

    Artifacts are deliberately not behind a StaticFiles mount: a mount serves by
    path alone and cannot check the row's `org_id` against the token claim, so
    knowing (or guessing) a key would be enough to read another partner's
    evidence. Every read goes through this row lookup instead.
    """
    store = get_store()
    try:
        artifact = store.get_artifact(principal.org_id, artifact_id)
    except KeyError:
        # Another org's artifact is indistinguishable from a missing one.
        raise HTTPException(status_code=404, detail="artifact not found") from None

    root = get_artifacts_dir().resolve()
    blob = (root / artifact.path).resolve()
    if not blob.is_relative_to(root) or not blob.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(blob, media_type=artifact.kind, filename=artifact.id)


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
def run_detail(
    run_id: str,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> HTMLResponse:
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
def test_detail(
    run_id: str,
    test_id: str,
    principal: Principal = Depends(current_principal),
) -> HTMLResponse:
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
def run_status(
    run_id: str,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> Response:
    # During submission the identifier may still be a job id. Keep this legacy
    # endpoint useful for queued/running work while retaining the finished-run
    # response for callers that already have a run id.
    try:
        job = get_store().get_job(principal.org_id, run_id)
    except KeyError:
        job = None
    if job is not None:
        payload = _job_status_payload(job)
        if "application/json" in request.headers.get("accept", "").lower():
            return JSONResponse(payload)
        message = escape(payload["message"])
        return HTMLResponse(
            f'<div id="run-status" data-poll-url="/runs/{escape(run_id)}/status" '
            f'aria-live="polite">{message}</div>'
        )

    rr, report = _load_run_or_404(principal.org_id, run_id)
    if "application/json" in request.headers.get("accept", "").lower():
        return JSONResponse(
            {
                "run_id": rr.run_id,
                "message": (
                    f"Finished at {rr.finished_at} - "
                    f"Gate: {'PASS' if report.gate_passed else 'BLOCK'}"
                ),
                "running": False,
            }
        )
    return _render("_status_fragment.html", run=rr, report=report)


def _safe_path(p: str) -> Path:
    resolved = Path(p).resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise HTTPException(status_code=400, detail="path escapes project root")
    return resolved


def _import_first_party(store: Store, org_id: str, target: str, packs: str) -> tuple[str, str]:
    """Copy a shipped target and pack into the caller's org as rows.

    The worker resolves jobs from the database only, so a run launched against
    a first-party target has to exist as rows before it can be queued. Both
    writes are idempotent upserts, so re-running the same pack is free.

    The config is stored **unexpanded**. Calling `load_target` here would
    interpolate `${VAR}` against the web process's environment, which fails on
    an unset var before T5's persistence guard ever runs, and would resolve a
    credential in the wrong process if the var *were* set. Only the worker
    resolves secrets, and only for the run it is executing.
    """
    target_path = _resolve_within_allowed(target)
    pack_dir = _resolve_within_allowed(packs)
    tests = discover(str(pack_dir))
    rows = []
    for test in tests:
        if not isinstance(test, TestCase):
            raise HTTPException(
                status_code=400,
                detail="Python test cases cannot be queued; use a YAML pack.",
            )
        rows.append(test.model_dump(mode="json", exclude_defaults=True))

    try:
        raw = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"malformed target: {exc}") from exc
    if not isinstance(raw, dict) or not raw.get("id"):
        raise HTTPException(status_code=400, detail="target config needs an 'id'")
    target_id = str(raw["id"])

    try:
        # save_target validates the config with env references masked, so this
        # is the guard that runs -- unset vars are irrelevant to it.
        store.save_target(
            org_id,
            target_id,
            target_id,
            raw,
            secret_ref=_first_party_secret_ref(raw),
            allowed_hosts=_first_party_hosts(raw),
        )
        store.save_pack(org_id, pack_dir.name, pack_dir.name, rows)
    except (LoaderError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return target_id, pack_dir.name


def _first_party_secret_ref(raw: dict) -> str | None:
    """Map a shipped config's single `${VAR}` reference to an `env://VAR` ref.

    First-party configs are trusted by provenance and carry at most one
    credential. A tenant-authored target supplies its own `secret_ref`; this
    only covers the shipped samples.
    """
    names = sorted(set(_ENV_REFS_RE.findall(json.dumps(raw))))
    if not names:
        return None
    if len(names) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"target references several secrets ({', '.join(names)}); "
            "register it as a target with an explicit secret_ref instead",
        )
    return f"env://{names[0]}"


def _first_party_hosts(raw: dict) -> list[str] | None:
    """Seed the egress allowlist from the endpoint the shipped config declares.

    This is provenance, not tenant input: the config ships in our image. A
    tenant-registered target must state its allowlist explicitly.
    """
    agent = raw.get("agent") or {}
    if not isinstance(agent, dict) or agent.get("type") != "http":
        return None
    host = urlsplit(str(agent.get("endpoint", ""))).hostname
    return [host] if host else []


@app.post("/runs")
def run_again(
    target: str = Form(...),
    packs: str = Form(...),
    # Read by require_admin off the form body; unused here.
    csrf_token: str = Form(""),  # noqa: ARG001
    principal: Principal = Depends(require_admin),
) -> RedirectResponse:
    """Queue a run. The worker executes it; this handler never blocks on an agent."""
    store = get_store()
    target_id, pack_id = _import_first_party(store, principal.org_id, target, packs)
    job_id = store.enqueue_job(
        principal.org_id, target_id, pack_id, created_by=principal.subject
    )
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


_JOB_MESSAGES = {
    "queued": "Queued...",
    "running": "Running...",
    "done": "Finished",
    "failed": "Failed",
}


def _job_status_payload(job) -> dict[str, object]:
    message = _JOB_MESSAGES.get(job.state, job.state)
    if job.state == "failed" and job.error:
        message = f"Failed: {job.error}"
    return {
        "job_id": job.id,
        "run_id": job.run_id or "",
        "state": job.state,
        "message": message,
        "running": job.state in ("queued", "running"),
    }


def _load_job_or_404(org_id: str, job_id: str):
    try:
        return get_store().get_job(org_id, job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found") from None


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: str, principal: Principal = Depends(current_principal)) -> HTMLResponse:
    return _render("job.html", job=_load_job_or_404(principal.org_id, job_id))


@app.get("/jobs/{job_id}/status")
def job_status(job_id: str, principal: Principal = Depends(current_principal)) -> JSONResponse:
    """Return the real queued/running/done state for a job."""
    job = _load_job_or_404(principal.org_id, job_id)
    return JSONResponse(_job_status_payload(job))


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
    browser_navigation = request.method in {"GET", "HEAD"} and (
        "text/html" in request.headers.get("accept", "").lower()
        or request.headers.get("accept", "") == "*/*"
    )
    public_auth_paths = {"/login", "/auth/callback"}
    if (
        exc.status_code == 401
        and auth_enabled()
        and browser_navigation
        and request.url.path not in public_auth_paths
    ):
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        return RedirectResponse(f"/login?next={quote(next_url, safe='')}", status_code=303)
    return _render(
        "error.html",
        status_code=exc.status_code,
        display_status=exc.status_code,
        detail=exc.detail,
        active="dashboard",
    )
