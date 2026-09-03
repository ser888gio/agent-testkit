"""JSON API for the React dashboard.

The SPA under ``frontend/spa`` renders every page; this module is its only data
source. Each endpoint returns the same derivation the React pages use
render — ``core.runview`` still owns it — serialized to JSON instead of templated.

Constraints carried over from the page routes, unchanged:

- Every route takes a ``Principal``; reads included. Mutations go through
  ``require_admin``, which enforces the admin role and (for browser sessions)
  CSRF via the ``x-csrf-token`` header.
- Every ``Store`` call is scoped with ``principal.org_id``.
- Nothing here writes files or dials an agent; evidence was redacted before it
  reached the store and is served exactly as stored.
- Run policy -- resolving target/pack paths, seeding a target's egress
  allowlist, checking a client's test ids against the pack -- lives in
  ``core.intake``, not in these handlers. ``IntakeError`` becomes a 400 via the
  handler in ``app.py``.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import yaml
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from agentaudit.core import llm, runview
from agentaudit.core.assertions import REGISTRY as ASSERTION_REGISTRY
from agentaudit.core.attacks import split_variant
from agentaudit.core.config import known_sandboxes
from agentaudit.core.evolve import (
    GENERATED_PREFIX,
    PROMOTED_PREFIX,
    promotable,
    promoted_id,
)
from agentaudit.core.findings import order_by_failure
from agentaudit.core.intake import is_offerable_target, is_pack_dir, register_http_target
from agentaudit.core.intake import queue_run as intake_queue_run
from agentaudit.core.loader import LoaderError, discover
from agentaudit.core.profile import AgentProfile
from agentaudit.core.regressions import compare
from agentaudit.core.schema import Category, Risk, TestCase
from agentaudit.core.store import DISCOVERY_PACK_ID
from agentaudit.core.timeline import build as build_timeline
from agentaudit.core.timeline import window as window_timeline
from agentaudit.reports.charts import bar_rows, donut_segments, sparkline_points
from agentaudit.reports.html import to_html
from agentaudit.reports.json import to_json
from agentaudit.reports.junit import to_junit
from agentaudit.reports.md import to_markdown
from agentaudit.reports.pdf import to_pdf
from agentaudit.web.auth import Principal, auth_enabled, current_principal, require_admin
from agentaudit.web.runtime import (
    PACKAGE_DIR,
    USER_PACK_ID,
    get_artifacts_dir,
    get_store,
    shipped_tests,
)

router = APIRouter(prefix="/api")

STATUS_LABELS = {
    "all": "All statuses",
    "failed": "Failed",
    "error": "Error",
    "passed": "Passed",
    "skipped": "Skipped",
}

BAD_STATUSES = runview.BAD_STATUSES


# ---------------------------------------------------------------------------
# Serialization helpers


def _serialize(value):
    """Recursively turn pydantic models / dataclasses into JSON-safe values."""
    if hasattr(value, "model_dump"):
        return _serialize(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _run_view(row: dict) -> dict:
    """A ``runview.run_row`` result without the raw ``Store`` row object."""
    view = {key: value for key, value in row.items() if key != "row"}
    return _serialize(view)


def _load_run_or_404(org_id: str, run_id: str):
    store = get_store()
    try:
        return store.get_run(org_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found") from exc


# Sanity bound on a caller-supplied job budget, not a tuning knob.
MAX_JOB_TIMEOUT_SECONDS = 24 * 60 * 60

_JOB_MESSAGES = {
    "queued": "Queued...",
    "running": "Running...",
    "done": "Finished",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "expired": "Timed out",
}


def _job_payload(job) -> dict:
    message = _JOB_MESSAGES.get(job.state, job.state)
    if job.state == "failed" and job.error:
        message = f"Failed: {job.error}"
    elif job.state == "running" and job.tests_total:
        message = f"Running... {job.tests_done} of {job.tests_total} tests"
    recent = json.loads(job.progress_json) if job.progress_json else []
    row = asdict(job) if is_dataclass(job) else dict(job)
    row.update(
        {
            "message": message,
            "running": job.state in ("queued", "running"),
            "recent": recent,
            "tests_total": job.tests_total or 0,
            # Test ids and status words only -- progress carries no agent output.
            "recent_test_ids": [entry.get("test_id") for entry in recent],
        }
    )
    return _serialize(row)


def _load_job_or_404(org_id: str, job_id: str):
    try:
        return get_store().jobs.get(org_id, job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found") from None


# ---------------------------------------------------------------------------
# Session / chrome


@router.get("/session")
def session_info(principal: Principal = Depends(current_principal)) -> dict:
    """Who the SPA is acting as, plus the CSRF token mutations must echo."""
    return {
        "org_id": principal.org_id,
        "subject": principal.subject,
        "email": principal.email,
        "roles": sorted(principal.roles),
        "auth_method": principal.auth_method,
        "csrf_token": principal.csrf_token,
        "admin": principal.can_mutate,
        "oidc_enabled": auth_enabled(),
    }


# ---------------------------------------------------------------------------
# Analytics (home page)


@router.get("/analytics")
def analytics(principal: Principal = Depends(current_principal)) -> dict:
    store = get_store()
    org = principal.org_id
    trend = store.score_trend(org, limit=30)
    rows = store.list_runs(org, limit=100)
    gates = sum(1 for r in rows if r.status not in BAD_STATUSES)
    latest = trend[-1]["score"] if trend else 0
    previous = trend[-2]["score"] if len(trend) > 1 else latest
    return {
        "trend": _serialize(trend),
        "sparkline": sparkline_points([p["score"] for p in trend]),
        "categories": _serialize(bar_rows(store.category_failure_rates(org))),
        "flaky": _serialize(store.flakiest_tests(org, limit=8)),
        "risks": _serialize(donut_segments(store.risk_breakdown(org))),
        "totals": {
            "runs": len(rows),
            "agents": len({r.agent_id for r in rows}),
            "gate_rate": round(gates / len(rows) * 100) if rows else 0,
            "critical": sum(r.score.get("critical_failures", 0) for r in rows),
            "latest_score": latest,
            "delta": latest - previous,
        },
    }


# ---------------------------------------------------------------------------
# Runs


@router.get("/runs")
def list_runs(
    q: str = "",
    status: str = "all",
    agent: str = "all",
    sort: str = "attention",
    principal: Principal = Depends(current_principal),
) -> dict:
    rows = get_store().list_runs(principal.org_id, limit=100)
    view = runview.dashboard(rows, q=q, status=status, agent=agent, sort=sort)
    return {
        "runs": [_run_view(r) for r in view["runs"]],
        "all_runs": [_run_view(r) for r in view["all_runs"]],
        "attention": [_run_view(r) for r in view["attention"]],
        "agents": view["agents"],
        "stats": view["stats"],
        "filters": {"q": q, "status": status, "agent": agent, "sort": sort},
        "status_labels": STATUS_LABELS,
    }


@router.get("/runs/{run_id}")
def run_detail(
    run_id: str,
    q: str = "",
    status: str = "all",
    category: str = "all",
    principal: Principal = Depends(current_principal),
) -> dict:
    rr, report = _load_run_or_404(principal.org_id, run_id)
    view = runview.detail(rr, q=q, status=status, category=category)
    plan = get_store().get_run_plan(principal.org_id, run_id)
    return _serialize(
        {
            "run": rr,
            "report": report,
            # Failure-first ordering comes from runview/findings, preserved here.
            "results": [r["result"] for r in view["result_rows"]],
            "matrix": view["matrix"],
            "categories": view["categories"],
            "duration_ms": view["duration_ms"],
            "plan": plan,
            "filters": {"q": q, "status": status, "category": category},
            "status_labels": STATUS_LABELS,
        }
    )


@router.get("/runs/{run_id}/harness")
def run_harness(run_id: str, principal: Principal = Depends(current_principal)) -> dict:
    run, report = _load_run_or_404(principal.org_id, run_id)
    return _serialize(runview.harness(run, report))


@router.get("/runs/{run_id}/tests/{test_id}")
def test_detail(
    run_id: str,
    test_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    rr, _report = _load_run_or_404(principal.org_id, run_id)
    result = next((r for r in rr.results if r.test_id == test_id), None)
    if result is None:
        raise HTTPException(status_code=404, detail=f"test '{test_id}' not found in run '{run_id}'")
    ordered = order_by_failure(rr.results)
    idx = next(i for i, r in enumerate(ordered) if r.test_id == test_id)
    # Attack variants keep their base test's rationale: the transform did not
    # change why the test was worth running.
    base_id = split_variant(test_id)[0]
    plan = get_store().get_run_plan(principal.org_id, run_id)
    selection = next(
        (s for s in (plan.selected if plan else []) if s.test_id in (test_id, base_id)),
        None,
    )
    history = get_store().test_history(
        principal.org_id, test_id, agent_id=rr.agent_name, limit=20
    )
    timeline = window_timeline(build_timeline(result))
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
        {
            "name": "Timeline",
            "state": "Available" if len(timeline["turns"]) >= 2 else "Unavailable",
            "detail": "Turn-by-turn requests and sandbox events for this test.",
        },
    ]
    return _serialize(
        {
            "run": rr,
            "result": result,
            "selection": selection,
            "previous_result": ordered[idx - 1] if idx > 0 else None,
            "next_result": ordered[idx + 1] if idx + 1 < len(ordered) else None,
            "history": history,
            "timeline": timeline if len(timeline["turns"]) >= 2 else None,
            "artifact_states": artifact_states,
        }
    )


# Reuses the CLI's renderers so a downloaded report is byte-identical to
# `agentaudit report --format ...`. Redaction already happened before the run
# was stored, so these render redacted evidence by construction.
_EXPORT_FORMATS = {
    "md": (to_markdown, "text/markdown; charset=utf-8", "md"),
    "json": (to_json, "application/json", "json"),
    "junit": (to_junit, "application/xml", "xml"),
    "html": (to_html, "text/html; charset=utf-8", "html"),
    # Renders to bytes rather than str; Response accepts either.
    "pdf": (to_pdf, "application/pdf", "pdf"),
}


@router.get("/runs/{run_id}/export/{fmt}")
def export_run(
    run_id: str,
    fmt: str,
    principal: Principal = Depends(current_principal),
) -> Response:
    if fmt not in _EXPORT_FORMATS:
        raise HTTPException(status_code=404, detail=f"unknown format '{fmt}'")
    run, report = _load_run_or_404(principal.org_id, run_id)
    render, media_type, suffix = _EXPORT_FORMATS[fmt]
    return Response(
        content=render(run, report),
        media_type=media_type,
        headers={
            "content-disposition": (
                f'attachment; filename="agentaudit-{run_id[:8]}.{suffix}"'
            )
        },
    )


@router.get("/compare")
def compare_runs(
    a: str,
    b: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    before, before_score = _load_run_or_404(principal.org_id, a)
    after, after_score = _load_run_or_404(principal.org_id, b)
    return {"diff": _serialize(compare(before, after, before_score, after_score))}


# ---------------------------------------------------------------------------
# Agents


@router.get("/agents")
def agents_list(principal: Principal = Depends(current_principal)) -> dict:
    store = get_store()
    org = principal.org_id
    rows = []
    for a in store.list_agents(org):
        latest = store.list_runs(org, a.id, limit=1)
        rows.append(
            {
                "agent": a,
                "latest": latest[0] if latest else None,
                "run_count": store.run_count(org, a.id),
            }
        )
    return {"agent_rows": _serialize(rows)}


# Registered before /agents/{agent_id:path} below so "register-options" is
# never read as an agent id.
@router.get("/agents/register-options")
def register_options(principal: Principal = Depends(current_principal)) -> dict:  # noqa: ARG001
    return {"sandboxes": list(known_sandboxes())}


class RegisterAgentBody(BaseModel):
    target_id: str
    endpoint: str
    sandbox: str = ""
    method: str = "POST"
    text_path: str = "$.text"


@router.post("/agents/register")
def register_agent(body: RegisterAgentBody, principal: Principal = Depends(require_admin)) -> dict:
    """Persist a tenant-authored HTTP target. Policy lives in `core.intake`."""
    target_id = register_http_target(
        get_store(),
        principal.org_id,
        target_id=body.target_id,
        endpoint=body.endpoint,
        sandbox=body.sandbox,
        method=body.method,
        text_path=body.text_path,
    )
    return {"agent_id": quote(target_id)}


@router.get("/agents/{agent_id:path}")
def agent_detail(agent_id: str, principal: Principal = Depends(current_principal)) -> dict:
    store = get_store()
    org = principal.org_id
    runs = store.list_runs(org, agent_id)
    matrix = store.pass_fail_matrix(org, agent_id)
    latest_run_id = runs[0].id if runs else None
    run_views = [_run_view(runview.run_row(r)) for r in runs]
    # An agent id is the target id it was run against, so the profile keys off
    # the same value. CLI-launched agents have no target row; offer profiling
    # only when the row exists rather than letting it 404.
    try:
        stored_profile = store.get_target_profile(org, agent_id)
        registered = True
    except KeyError:
        stored_profile = None
        registered = False
    if isinstance(stored_profile, tuple):
        profile, profiled_at = stored_profile
    else:  # registered target that has never been profiled
        profile = None
        profiled_at = None
    capabilities: set[str] = set()
    if profile is not None:
        capabilities = AgentProfile.model_validate(profile).capabilities()
    return _serialize(
        {
            "agent_id": agent_id,
            "runs": run_views,
            "matrix": matrix,
            "latest_run_id": latest_run_id,
            "profile": profile,
            "profiled_at": profiled_at,
            "capabilities": sorted(capabilities),
            "registered": registered,
            "allowed_hosts": (
                store.get_target_allowed_hosts(org, agent_id) if registered else []
            ),
        }
    )


class AllowlistBody(BaseModel):
    allowed_hosts: str = ""


@router.post("/agents/{agent_id:path}/allowlist")
def update_allowlist(
    agent_id: str,
    body: AllowlistBody,
    principal: Principal = Depends(require_admin),
) -> dict:
    """Edit the hosts a registered target may be dialled at.

    This is the one piece of run configuration that is genuinely per-tenant;
    the process-level settings on /settings are deployment-owned and read-only
    on purpose.
    """
    store = get_store()
    try:
        raw = store.get_target(principal.org_id, agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown target '{agent_id}'") from None
    hosts = [h.strip() for h in body.allowed_hosts.replace(",", " ").split() if h.strip()]
    store.save_target(
        principal.org_id,
        agent_id,
        agent_id,
        raw,
        secret_ref=store.get_target_secret_ref(principal.org_id, agent_id),
        allowed_hosts=hosts,
    )
    return {"saved": True}


@router.post("/agents/{agent_id:path}/discover")
def discover_agent(agent_id: str, principal: Principal = Depends(require_admin)) -> dict:
    """Queue a profile refresh. The worker probes; this handler never dials out."""
    store = get_store()
    try:
        store.get_target(principal.org_id, agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown target '{agent_id}'") from None
    job_id = store.jobs.enqueue_discovery(principal.org_id, agent_id, created_by=principal.subject)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Connect (run configuration)


def _pack_tests(root: Path, pack_roots: list[str]) -> dict[str, list[dict]]:
    """Test metadata for every discoverable pack, keyed by pack path."""
    pack_tests: dict[str, list[dict]] = {}
    for rel in pack_roots:
        try:
            cases = discover(str(root / rel))
        except LoaderError:
            continue
        pack_tests[rel] = [
            {
                "id": t.id,
                "description": t.description,
                "category": t.category.value,
                "risk": t.risk.value,
            }
            for t in cases
            if isinstance(t, TestCase)
        ]
    return pack_tests


def _defaults_from_last_job(
    root: Path,
    targets: list[str],
    pack_roots: list[str],
    registered_targets: list[dict],
    last_job,
) -> tuple[str | None, str | None]:
    """The (target, pack) to preselect, derived from this org's last job.

    A shipped config file wins when one carries the job's target id; otherwise
    the id is matched against the tenant's registered rows.
    """
    for rel in targets:
        try:
            raw = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(raw, dict) and str(raw.get("id")) == last_job.target_id:
            default_target = rel
            break
    else:
        default_target = next(
            (t["id"] for t in registered_targets if t["id"] == last_job.target_id),
            None,
        )
    default_pack = next(
        (rel for rel in pack_roots if Path(rel).name == last_job.pack_id),
        None,
    )
    return default_target, default_pack


@router.get("/connect-options")
def connect_options(principal: Principal = Depends(current_principal)) -> dict:  # noqa: ARG001
    root = PACKAGE_DIR.parent
    targets = sorted(
        p.relative_to(root).as_posix()
        for p in (PACKAGE_DIR / "config").glob("*.yaml")
        if is_offerable_target(p)
    )
    pack_roots = sorted(
        p.relative_to(root).as_posix() for p in (PACKAGE_DIR / "packs").iterdir() if is_pack_dir(p)
    )
    pack_tests = _pack_tests(root, pack_roots)
    store = get_store()
    # Targets the tenant registered by endpoint URL: runnable straight from
    # their stored rows, no shipped config needed.
    registered_targets = [
        {"id": row.id, "name": row.name} for row in store.list_targets(principal.org_id)
    ]
    # Default to whatever this org last launched -- derived, not a stored
    # preference.
    last_jobs = store.jobs.list_recent(principal.org_id, limit=1)
    default_target = default_pack = None
    if last_jobs:
        default_target, default_pack = _defaults_from_last_job(
            root, targets, pack_roots, registered_targets, last_jobs[0]
        )
    return {
        "targets": targets,
        "registered_targets": registered_targets,
        "pack_roots": pack_roots,
        "default_target": default_target,
        "default_pack": default_pack,
        "pack_tests": pack_tests,
    }


class EnqueueRunBody(BaseModel):
    target: str
    packs: str
    test_ids: list[str] = []
    timeout_seconds: int | None = Field(default=None, gt=0, le=MAX_JOB_TIMEOUT_SECONDS)


@router.post("/runs/enqueue")
def enqueue_run(body: EnqueueRunBody, principal: Principal = Depends(require_admin)) -> dict:
    """Queue a run. The worker executes it; this handler never blocks on an agent."""
    return {
        "job_id": intake_queue_run(
            get_store(),
            principal.org_id,
            target=body.target,
            packs=body.packs,
            test_ids=body.test_ids,
            timeout_seconds=body.timeout_seconds,
            created_by=principal.subject,
        )
    }


# ---------------------------------------------------------------------------
# Jobs


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, principal: Principal = Depends(current_principal)) -> dict:
    job = _load_job_or_404(principal.org_id, job_id)
    payload = _job_payload(job)
    # A discovery job produces a profile, not a run: the sentinel pack id is an
    # implementation detail and must not surface as if it were a pack.
    payload["discovery"] = job.pack_id == DISCOVERY_PACK_ID
    return payload


@router.get("/jobs/{job_id}/status")
def job_status(job_id: str, principal: Principal = Depends(current_principal)) -> dict:
    return _job_payload(_load_job_or_404(principal.org_id, job_id))


@router.post("/jobs/{job_id}/rerun")
def rerun_job(job_id: str, principal: Principal = Depends(require_admin)) -> dict:
    """Queue the same target/pack/selection again as a new job.

    Re-enqueues off the stored job row, so nothing is re-resolved from a
    client-supplied path and the original job stays as it is.
    """
    job = _load_job_or_404(principal.org_id, job_id)
    test_ids = json.loads(job.test_ids_json) if job.test_ids_json else None
    new_id = get_store().jobs.enqueue(
        principal.org_id,
        job.target_id,
        job.pack_id,
        created_by=principal.subject,
        test_ids=test_ids,
        timeout_seconds=job.timeout_seconds,
    )
    return {"job_id": new_id}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, principal: Principal = Depends(require_admin)) -> dict:
    """Request cancellation. Cooperative for a running job; finished jobs stay."""
    _load_job_or_404(principal.org_id, job_id)
    get_store().jobs.request_cancel(principal.org_id, job_id)
    return {"cancelled": True}


# ---------------------------------------------------------------------------
# Test library


@router.get("/tests")
def tests_page(
    q: str = "",
    status: str = "all",
    risk: str = "all",
    category: str = "all",
    principal: Principal = Depends(current_principal),
) -> dict:
    store = get_store()
    org = principal.org_id
    rows = runview.library(
        shipped_tests(),
        store.list_authored_tests(org),
        store.list_tests(org),
    )
    rows = runview.filter_rows(rows, q=q, status=status)
    if risk != "all":
        rows = [r for r in rows if r.get("risk") == risk]
    if category != "all":
        rows = [r for r in rows if r.get("category") == category]
    rows = runview.sort_library([{k: v for k, v in row.items() if k != "result"} for row in rows])
    return {
        "tests": _serialize(rows),
        "categories": [c.value for c in Category],
        "risks": [r.value for r in Risk],
        "status_labels": STATUS_LABELS,
        "filters": {"q": q, "status": status, "risk": risk, "category": category},
    }


@router.get("/test-form-options")
def test_form_options(principal: Principal = Depends(current_principal)) -> dict:  # noqa: ARG001
    return {
        "categories": [c.value for c in Category],
        "risks": [r.value for r in Risk],
        "assertions": sorted(ASSERTION_REGISTRY),
    }


class CreateTestBody(BaseModel):
    test_id: str
    category: str
    risk: str
    input: str
    assertion_name: str
    assertion_args: str = ""


@router.post("/tests")
def create_test(body: CreateTestBody, principal: Principal = Depends(require_admin)) -> dict:
    args: dict = {}
    if body.assertion_args.strip():
        try:
            parsed = yaml.safe_load(body.assertion_args)
        except yaml.YAMLError as exc:
            raise HTTPException(
                status_code=400, detail=f"Assertion args are not valid YAML: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=400,
                detail='Assertion args must be a YAML mapping, e.g. {values: ["sk-"]}',
            )
        args = parsed

    raw = {
        "id": body.test_id,
        "category": body.category,
        "risk": body.risk,
        "input": body.input,
        "assertions": [{"name": body.assertion_name, "args": args}],
    }
    try:
        test_case = TestCase.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid test: {exc.errors()[0]['msg']}"
        ) from exc

    if body.assertion_name not in ASSERTION_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown assertion '{body.assertion_name}'")

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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"created": True}


# ---------------------------------------------------------------------------
# Generated-test review queue


@router.get("/generated")
def generated_page(principal: Principal = Depends(current_principal)) -> dict:
    store = get_store()
    try:
        rows = store.get_pack_tests(principal.org_id, GENERATED_PREFIX)
    except KeyError:
        rows = []
    statuses = {t["test_id"]: t["latest_status"] for t in store.list_tests(principal.org_id)}
    return {"candidates": _serialize(promotable(rows, statuses))}


class TestIdBody(BaseModel):
    test_id: str


@router.post("/generated/promote")
def promote_test(body: TestIdBody, principal: Principal = Depends(require_admin)) -> dict:
    """Move one generated test into the reviewed pack.

    This mutates the audited baseline, so it is admin-gated and CSRF-protected
    like every other mutation here. The id changes exactly once, here, and is
    frozen afterwards.
    """
    store = get_store()
    try:
        rows = store.get_pack_tests(principal.org_id, GENERATED_PREFIX)
    except KeyError:
        raise HTTPException(status_code=404, detail="No generated tests.") from None
    row = next((r for r in rows if r.get("id") == body.test_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown test {body.test_id}.")
    promoted = {**row, "id": promoted_id(body.test_id)}
    store.ensure_pack(principal.org_id, PROMOTED_PREFIX, "Promoted tests (reviewed)")
    try:
        store.save_pack_test(
            principal.org_id,
            PROMOTED_PREFIX,
            promoted,
            created_by=principal.subject,
            created_by_email=principal.email,
        )
    except LoaderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.delete_pack_test(principal.org_id, GENERATED_PREFIX, body.test_id)
    return {"promoted_to": promoted["id"]}


@router.post("/generated/reject")
def reject_test(body: TestIdBody, principal: Principal = Depends(require_admin)) -> dict:
    get_store().delete_pack_test(principal.org_id, GENERATED_PREFIX, body.test_id)
    return {"rejected": body.test_id}


# ---------------------------------------------------------------------------
# Settings


class LLMRoleBody(BaseModel):
    """One role's model. `api_key` omitted keeps whatever key is already stored."""

    endpoint: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)


class LLMSettingsBody(BaseModel):
    attacker: LLMRoleBody | None = None
    judge: LLMRoleBody | None = None


@router.get("/settings")
def settings_info(principal: Principal = Depends(current_principal)) -> dict:
    """The tenant's own model configuration, plus the deployment default it falls back to.

    Keys are never returned -- only whether one is stored -- for the same reason
    `llm.describe` never returned one.
    """
    return {
        "llm": get_store().get_llm_settings(principal.org_id),
        "fallback": llm.describe(),
        "default_endpoint": llm.DEFAULT_ENDPOINT,
    }


@router.put("/settings/llm")
def save_llm_settings(
    body: LLMSettingsBody, principal: Principal = Depends(require_admin)
) -> dict:
    """Replace this org's model configuration. A null role clears it."""
    store = get_store()
    for role, spec in (("attacker", body.attacker), ("judge", body.judge)):
        if spec is None:
            store.delete_llm_settings(principal.org_id, role)
            continue
        # Scheme-only, deliberately: this is the operator's own model host, not a
        # partner-supplied target, so it has no allowlist to sit inside and the
        # DNS-pinning that `validate_endpoint` does belongs at dial time. https
        # is still required -- the key travels in that request.
        parts = urlsplit(spec.endpoint)
        allow_http = os.environ.get("AGENTAUDIT_EGRESS_ALLOW_LOCAL") == "1"
        if parts.scheme not in ("https", *(("http",) if allow_http else ())):
            raise HTTPException(status_code=400, detail=f"{role} endpoint must use https")
        if not parts.hostname or parts.username or parts.password:
            raise HTTPException(
                status_code=400, detail=f"{role} endpoint must be a URL without credentials"
            )
        store.save_llm_settings(
            principal.org_id, role, spec.endpoint, spec.model, spec.api_key or None
        )
    return {"llm": store.get_llm_settings(principal.org_id)}


# ---------------------------------------------------------------------------
# Artifacts


@router.get("/artifacts/{artifact_id}")
def download_artifact(
    artifact_id: str, principal: Principal = Depends(current_principal)
) -> Response:
    """The only permitted way to serve a blob.

    Artifacts are deliberately not behind a StaticFiles mount: a mount serves by
    path alone and cannot check the row's `org_id` against the token claim.
    Every read goes through this row lookup instead.
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
