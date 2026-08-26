# Plan 004: Add frame-protection headers to the dashboard

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat e4cfe48..HEAD -- frontend/agentaudit/web/app.py tests/test_web.py`
> On any mismatch with "Current state" below, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `e4cfe48`, 2026-08-26

## Why this matters

The dashboard serves an authenticated multi-tenant control plane but sets no
`Content-Security-Policy: frame-ancestors` / `X-Frame-Options` header, so any
site can embed it in an iframe. Mutation routes are CSRF-protected by a token
the SPA itself fetches and echoes — which means a framed, logged-in admin
session supplies its own valid CSRF token, and clickjacking can drive
state-changing actions (enqueue runs, promote/reject generated tests, register
agents, cancel jobs). Header-only fix; no legitimate embedding use-case exists
in the SPA sources.

## Current state

- `frontend/agentaudit/web/app.py` — FastAPI app construction and SPA shell
  serving. Verified excerpt at commit `e4cfe48` (~lines 61-70): the app is
  built with no middleware:

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

- `frontend/agentaudit/web/auth.py` — CSRF dependency (`require_admin`,
  ~235-249) compares `x-csrf-token` against the session token; the SPA echoes
  the token from `/api/session`.
- `tests/test_web.py` — TestClient-driven API tests; add the header assertion
  here.
- Repo web conventions (`frontend/agentaudit/web/CLAUDE.md`): every route
  takes a Principal; app holds routing not derivation. A tiny pure-header
  middleware belongs in app.py alongside routing concerns.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Web tests | `uv run --extra dev pytest tests/test_web.py` | all pass |
| Security suite | `uv run --extra dev pytest tests/test_security_p0.py` | all pass |
| Lint | `uv run ruff check frontend/agentaudit/web/app.py tests/test_web.py` | exit 0 |

## Scope

**In scope**:
- `frontend/agentaudit/web/app.py` (add one middleware immediately after app creation)
- `tests/test_web.py` (add assertions)

**Out of scope**:
- `Cache-Control` hardening (separate finding, do NOT bundle).
- Any auth/CSRF logic change.
- SPA source.

## Git workflow

- Branch: `advisor/004-frame-headers`
- Commit style: short imperative subject.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a response-header middleware

In `frontend/agentaudit/web/app.py`, directly after the `FastAPI(...)` /
`include_router` block shown above, add a Starlette BaseHTTPMiddleware:

```python
from starlette.middleware.base import BaseHTTPMiddleware


@app.middleware("http")
async def frame_protection(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    return response
```

(Import style must match the file's existing import ordering — ruff I will tell you.)

**Verify**: `uv run ruff check frontend/agentaudit/web/app.py` → exit 0;
then `uv run python -c "import agentaudit.web.app"` → exits 0.

### Step 2: Assert headers on representative responses

In `tests/test_web.py`, add one test asserting that BOTH the SPA shell HTML
response and a JSON API response carry both headers (use the client fixture /
auth pattern used by neighboring tests). Also assert the login page (public)
carries them — cheap consistency.

**Verify**: `uv run --extra dev pytest tests/test_web.py -k frame` → passes

### Step 3: Full-suite sanity

The route-table auth walk (`test_every_route_requires_a_token`) must remain
green; middleware adds no routes so it should be untouched.

**Verify**: `uv run --extra dev pytest tests/test_web.py tests/test_security_p0.py` → all pass

## Test plan

- New test per Step 2 in `tests/test_web.py`: happy-path header presence on
  HTML + JSON + public login responses.
- Verification: full web + security suites green.

## Done criteria

- [ ] Both headers present on shell/API/login responses (new test proves it)
- [ ] `uv run --extra dev pytest tests/test_web.py tests/test_security_p0.py` exits 0
- [ ] `uv run ruff check frontend/agentaudit/web/app.py tests/test_web.py` exits 0
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:
- App construction doesn't match the excerpt (drift).
- Adding middleware breaks the SPA catch-all or static mounts in any way.
- An existing test asserts absence of these headers or exact header-set equality.

## Maintenance notes

- Reviewer should scrutinize: headers apply to error responses too (BaseHTTPMiddleware
  covers exceptions only if they don't bypass — confirm 500s still carry them,
  or accept the gap explicitly).
- Follow-up deferred: `Cache-Control: no-store` on `/api/*` (advisory finding #7) —
  same middleware could grow it, but land separately for reviewability.
