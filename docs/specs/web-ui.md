# feat/react-spa — Spec

**Rewrite of task 18 · Files:** `frontend/spa/**`, `agentaudit/web/api.py`,
`agentaudit/web/app.py`, `agentaudit/web/runtime.py`, `tests/test_web.py`

## Goal

The same dashboard, rewritten as a React single-page app.
FastAPI keeps auth, authorization, and derivation; it now serves JSON under
`/api/*` plus the built SPA bundle. No server-side templating remains.

## Architecture

| layer | location | owns |
|-------|----------|------|
| Pages | `frontend/spa/src/pages/*.tsx` (React 18 + TS + Vite) | rendering, filters, polling |
| JSON API | `frontend/agentaudit/web/api.py` | the same derivation the React pages do, serialized |
| Shell | `frontend/agentaudit/web/app.py` | auth routes, static mounts, SPA catch-all |
| Runtime | `frontend/agentaudit/web/runtime.py` | Store singleton, path safety |

Build: `npm ci && npm run build` in `frontend/spa` → output in
`web/spa_dist`, served at `/assets/*` with `index.html` handed out for every
application GET (behind a Principal, like every other read).

## Routes → page acceptance criteria (unchanged semantics)

| SPA route | API endpoint | must show |
|-----------|--------------|-----------|
| `/` | `GET /api/analytics` | trend sparkline, gate pass rate, **critical failure count**, failure rates by category/risk, flakiest tests |
| `/runs` | `GET /api/runs` | latest runs (agent, time, gate verdict), stats band, needs-attention queue, filters (q/status/agent/sort) |
| `/runs/:id` | `GET /api/runs/{run_id}` | score header; **category × test matrix**; **failed tests listed first**; plan rationale |
| `/runs/:id/tests/:test_id` | `GET /api/runs/{run_id}/tests/{test_id}` | input, **redacted** response, each assertion, sandbox diff, latency, cross-run history |
| `/runs/:id/harness` | `GET /api/runs/{run_id}/harness` | environment, skills, memory & context, chronological workflow; export links |
| `/agents` etc. | `GET /api/agents*` | agents + latest score; register-by-endpoint; connect/run form |
| `/tests`, `/tests/new` | `GET/POST /api/tests` | library with filters; authoring form storing DB rows |
| `/generated` | `GET /api/generated` + promote/reject | machine-authored queue; promote freezes the id |
| `/jobs/:id` | `GET /api/jobs/{job_id}(/status)` | live progress (2s polling), cancel |
| `/compare?a&b` | `GET /api/compare` | newly failing/passing, still failing, coverage change, score delta |
| `/settings` | `GET /api/settings` | deployment-owned runtime config (read-only) |

## Behavior

- All data comes from `Store` read helpers via `core.runview`. No business
  logic in components; no derivation in handlers.
- Colors stay semantic: passed=green, failed=red, error=amber, skipped=grey.
  Matrix cells link to test detail. The stylesheet (`static/style.css`) is
  shared unchanged; both themes keep their contrast guarantees.
- Evidence shown is whatever the store holds — already redacted; the UI shows
  `«redacted:…»` markers as-is and uses no HTML-injection sinks.
- Mutations are admin-gated; browser sessions echo the CSRF token from
  `/api/session` in `x-csrf-token`. Job progress polls every 2s while running
  and follows the job to its run when done.
- Unknown ids → JSON 404 `{detail}`; the SPA renders an empty-state error page.

## Tests required (FastAPI `TestClient` over `/api/*`)

- Seed the store with one run; `GET /api/runs` lists it with the critical count.
- `GET /api/runs/{id}` returns the matrix with failures ordered first.
- `GET /api/runs/{id}/tests/{tid}` carries redacted response, assertion details,
  latency.
- Unknown ids → 404. Every route 401s without a token (route-table walk).
- SPA sources keep their `data-testid` hooks and use no HTML injection sinks.

## Done when

With a seeded DB, `/api/runs` serves the run list + critical count, run detail
serves the category matrix (failures first), test detail serves redacted
evidence, assertions, sandbox diff, and latency — all rendered by the React SPA.
