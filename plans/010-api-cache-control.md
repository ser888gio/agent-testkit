# Plan 010: Mark authenticated API responses uncacheable

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**:
> `git diff --stat 5959852..HEAD -- frontend/agentaudit/web/app.py frontend/agentaudit/web/api.py tests/test_web.py`
> If any changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/004-frame-headers.md` — **sequencing only**, see below
- **Category**: security
- **Planned at**: commit `5959852`, 2026-08-29

### Note on the dependency

Plan 004 adds a response-header middleware to the same file
(`frontend/agentaudit/web/app.py`) immediately after app construction. These
two plans are logically independent but will collide in that one region of the
file. **Land 004 first**, then this plan, to avoid a merge conflict.

If 004 has already landed, you will find a `frame_protection` middleware there.
**Do not merge this plan's logic into it** — see step 1 for why they stay
separate.

## Why this matters

Every response from the authenticated JSON API — session details, run
evidence, agent configuration, generated test content — is served with no
`Cache-Control` header. HTTP's default for an un-hinted response is that
intermediaries and the browser may store it heuristically.

On a hosted, multi-tenant deployment (the target topology per
`docs/architecture.md`) that means audit evidence and session payloads can come
to rest in a shared cache. The `/api/session` response is the sharpest case: it
carries the CSRF token and the principal's identity. A cached copy served to
the wrong viewer is a cross-tenant disclosure, and it is the kind of finding
that is very cheap to prevent and very expensive to explain afterwards for a
product whose whole purpose is producing compliance evidence.

The fix is one header on one route prefix.

## Current state

- `frontend/agentaudit/web/app.py` — FastAPI app construction, login/logout
  routes, and the SPA shell. This is where middleware goes.
- `frontend/agentaudit/web/api.py` — the JSON API. Every route is mounted under
  a single prefixed router (`api.py:73`):

  ```python
  router = APIRouter(prefix="/api")
  ```

  Every route already carries a `Depends(...)` principal — there are no
  unauthenticated API routes. That is what makes a blanket rule on the prefix
  safe.

- `tests/test_web.py` — TestClient-driven API tests; header assertions go here.
- `tests/test_security_p0.py` — existing security-property tests; a reasonable
  alternative home if the assertions read better there.

Excerpt of app construction (`frontend/agentaudit/web/app.py:72-79`, verified
at `5959852`):

```python
app = FastAPI(
    title="agentaudit",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)
app.include_router(api_router)
```

Immediately after this, `app.py` mounts two `StaticFiles` apps:

```python
if (BASE_DIR / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
if SPA_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(SPA_DIST)), name="assets")
```

**These must stay cacheable.** The Vite bundle is content-hashed, so its assets
are safely and deliberately long-lived in cache. A blanket `no-store` across
the whole app would defeat that and make every page load re-download the
bundle. This is the single most important constraint in this plan.

### Repo conventions

Per `frontend/agentaudit/web/CLAUDE.md`: keep `app.py` thin — routing and
cross-cutting concerns only, no derivation logic. A pure header middleware fits
that. 100-char lines, ruff `E`/`F`/`I`/`B`/`UP`, four-space indent.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Web tests | `python -m pytest tests/test_web.py -q` | all pass |
| Security tests | `python -m pytest tests/test_security_p0.py -q` | all pass |
| Import check | `python -c "import agentaudit.web.app"` | exit 0, no output |
| Full suite | `python -m pytest` | exit 0 |
| Lint | `python -m ruff check .` | `All checks passed!` |

**Windows note**: call pytest as a module (`python -m pytest`). The
`uv run --extra dev pytest` console-script form fails on this platform with
`uv trampoline failed to canonicalize script path`. (Some earlier plans in this
directory show the `uv run` form; prefer the commands in this table.)

## Scope

**In scope** (the only files you should modify):
- `frontend/agentaudit/web/app.py`
- `tests/test_web.py` (or `tests/test_security_p0.py` — pick one, not both)

**Out of scope** (do NOT touch, even though they look related):
- `frontend/agentaudit/web/api.py` — do **not** add per-route `Response`
  parameters or decorate individual handlers. One middleware on the prefix is
  the whole fix; 60-odd route signatures is not.
- The `/static` and `/assets` mounts — see the constraint above. Leave them
  cacheable.
- The SPA shell HTML response — out of scope for this plan.
- Any auth, CSRF, or session logic.
- `frontend/spa/src/api.ts` — the client needs no change.

## Git workflow

- Branch: `fix/010-api-cache-control` (already created off `develop`).
- Suggested commit: `fix(web): mark API responses no-store`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a path-scoped cache-control middleware

In `frontend/agentaudit/web/app.py`, after `app.include_router(api_router)` and
**before** the `StaticFiles` mounts, add:

```python
@app.middleware("http")
async def no_store_api_responses(request: Request, call_next):
    # Scoped to /api on purpose: those responses carry session identity, the
    # CSRF token and audit evidence, none of which may come to rest in a shared
    # cache. The SPA bundle under /assets is content-hashed and must stay
    # cacheable, so this deliberately does not apply app-wide.
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
```

`Request` is already imported in `app.py` (`from fastapi import Depends,
FastAPI, HTTPException, Request, Response`) — add no new imports.

If plan 004 has landed and a `frame_protection` middleware is present, add this
as a **second, separate** middleware rather than extending it. They have
different scopes — frame protection is app-wide, this one is `/api`-only — and
folding a path condition into a middleware named for framing makes both harder
to reason about.

**Verify**:
```
python -c "import agentaudit.web.app"
python -m ruff check frontend/agentaudit/web/app.py
```
→ both exit 0.

### Step 2: Assert the header is present on API responses

Add one test asserting that a JSON API response carries
`Cache-Control: no-store`. Use `/api/session` — it is the response that most
needs the header and it is available to any authenticated principal.

Use the existing client fixture pattern in `tests/test_web.py` (search for
`_client(` — the same helper the enqueue tests use).

```python
def test_api_responses_are_not_cacheable(tmp_path, monkeypatch):
    """Session identity, the CSRF token and evidence must not come to rest in
    a shared cache on a hosted deployment."""
    client = _client(str(tmp_path / "cache.db"), monkeypatch)

    resp = client.get("/api/session")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
```

**Verify**: `python -m pytest tests/test_web.py -k not_cacheable -q` → passes.

### Step 3: Assert static assets stayed cacheable

This is the regression guard for the constraint in "Current state". Add to the
same test (or a second one) an assertion that a non-`/api` path does **not**
carry `no-store`:

```python
    shell = client.get("/")
    assert shell.headers.get("cache-control") != "no-store"
```

If the SPA bundle is not built in your environment, `/` returns the placeholder
HTML — that is fine, the assertion is about the header, not the body.

**Verify**: `python -m pytest tests/test_web.py -k not_cacheable -q` → still
passes.

### Step 4: Full verification

```
python -m pytest -q
python -m ruff check .
```

**Verify**: full suite green (allowing for plan 006's four failures if 006 has
not yet landed — and no others); ruff `All checks passed!`.

## Test plan

- **New tests**: one (optionally two), per steps 2–3:
  - `/api/session` carries `Cache-Control: no-store` — the fix.
  - a non-`/api` path does not — the guard against over-applying it.
- **Structural pattern**: the `_client(...)` fixture usage in
  `tests/test_web.py` (e.g. `test_post_runs_enqueues_without_executing`).
- **Existing tests that must keep passing**: all of `tests/test_web.py` and
  `tests/test_security_p0.py`. If plan 004 has landed, its frame-header test
  must still pass — proving the two middlewares compose.
- **Verification**: `python -m pytest tests/test_web.py tests/test_security_p0.py -q`
  → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -c "import agentaudit.web.app"` exits 0
- [ ] `python -m pytest tests/test_web.py tests/test_security_p0.py -q` exits 0
- [ ] `python -m pytest` is no worse than before your change
- [ ] `python -m ruff check .` exits 0
- [ ] `grep -c "no-store" frontend/agentaudit/web/app.py` returns `1`
- [ ] `grep -c "startswith(\"/api/\")" frontend/agentaudit/web/app.py` returns `1`
- [ ] A test asserting a non-`/api` path lacks `no-store` exists and passes
- [ ] `git status --short` shows exactly two modified files and no others
- [ ] `plans/README.md` status row for 010 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- Any existing `tests/test_web.py` or `tests/test_security_p0.py` test starts
  failing — most likely the middleware is applying more broadly than intended.
- You find an API route mounted outside the `/api` prefix (check
  `grep -n "APIRouter(" frontend/agentaudit/web/api.py` still shows
  `prefix="/api"`) — the path-scoped rule would miss it and the approach needs
  revisiting.
- The app-construction block does not match the "Current state" excerpt.
- You find yourself wanting to edit `api.py` route signatures, or to drop the
  `/api` path condition and apply `no-store` app-wide.

## Maintenance notes

- **The load-bearing constraint is the path scope.** Anyone who later
  "simplifies" this by removing the `startswith("/api/")` check will silently
  make the content-hashed SPA bundle uncacheable and slow every page load. The
  step-3 assertion exists specifically to fail if that happens — do not delete
  it as redundant.
- If an API route is ever mounted outside the `/api` prefix, it will not get
  the header. A route-table walk already exists in `tests/test_web.py`
  (the auth walk around line 683) and would be the natural place to also assert
  cache headers, should the surface grow.
- `no-store` (not `no-cache`) is the correct directive here: `no-cache` permits
  storage with revalidation, which still leaves the payload at rest in an
  intermediary.
- Reviewer should scrutinize: that `/assets` and `/static` responses are
  unaffected, and that no route handler signatures changed.
