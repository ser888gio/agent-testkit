# feat/web-ui — Spec

**Task 18 · Depends on: 13,12 · Files:** `agentkit/web/app.py`,
`agentkit/web/templates/*.html`, `agentkit/web/static/*`, `tests/test_web.py`

## Goal
A FastAPI + Jinja/HTMX dashboard (no JS build) over the `Store`, read-only for the MVP plus a
"run again" trigger.

## Routes → page acceptance criteria
| route | page | must show |
|-------|------|-----------|
| `GET /` | Dashboard | list of latest runs (agent, time, gate verdict), overall pass rate, **critical failure count** prominent |
| `GET /agents` | Agents | each agent + latest score/status |
| `GET /agents/{id}` | Agent detail | run history for the agent + latest pass/fail matrix |
| `GET /runs/{run_id}` | Run detail | score header (overall/pass rate/critical); **category × test matrix**; **failed tests listed first** |
| `GET /runs/{run_id}/tests/{test_id}` | Test detail | input, **redacted** response, each assertion (pass/fail + detail), **sandbox diff**, latency |
| `POST /runs?target=…` | Run again | triggers a run (HTMX), then redirects/swaps to the new run detail |
| `GET /runs/{run_id}/status` | poll fragment | HTMX polling target for an in-progress run |

## Behavior
- All data comes from `Store` read helpers (task 13). No business logic in templates.
- Colors: passed=green, failed=red, error=amber, skipped=grey. Matrix cells link to test detail.
- Evidence shown is whatever the store holds — already redacted; the UI never un-redacts and
  shows `«redacted:…»` markers as-is.
- `POST /runs` runs synchronously for the MVP if fast, else kicks a background task and the
  status fragment polls until `finished_at` is set.

## Failure behavior
- Unknown `run_id`/`test_id` → 404 page (not a stack trace).
- Empty DB → dashboard shows an empty state with a "run your first pack" hint.

## Tests required (FastAPI `TestClient`)
- Seed the store with one run; `GET /` shows it and the critical count.
- `GET /runs/{id}` renders the category matrix and lists a failed test before passed ones.
- `GET /runs/{id}/tests/{tid}` shows redacted response + assertion details + latency.
- Unknown ids → 404.

## Done when
With a seeded DB, the dashboard renders latest runs + critical count, run detail shows the
category matrix (failures first), and test detail shows redacted evidence, assertions, sandbox
diff, and latency.
