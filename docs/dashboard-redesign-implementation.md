# Dashboard redesign implementation report

Date: 2026-07-17

Branch: `feat/dashboard-redesign-ui`

## Scope applied

The research package in `dashboard-redesign-research/` was used for its transferable
Playwright/Cypress UX patterns:

- overview to prioritized queue to detail to evidence
- failure-first triage
- searchable and filterable run/test lists
- persistent context while drilling into failed tests
- explicit artifact availability states
- responsive tables that become readable mobile rows
- keyboard-visible focus and non-color-only status labels

The RS Generator-specific items in that plan were not implemented because this repository is
Agent Testkit, a FastAPI/Jinja dashboard over agents, runs, tests and stored results.

## Explicit exclusions

Per user instruction, this implementation does not add:

- Microsoft Entra ID
- voice mode
- MediaRecorder, AudioContext, WebSocket voice flows, or related permissions UI

## Implemented UX

- Dashboard summary cards for runs, failed gates, critical failures and average score.
- Needs-attention queue for failed or critical runs.
- Search, status, agent and sort filters on the dashboard.
- Search/status/risk/category filters on the tests page.
- Run detail with gate summary, evidence map, failures-for-review queue and filtered results.
- Test evidence page with status/risk/latency summary, assertion outcomes, artifact availability,
  request/response evidence and previous/next navigation.
- Agent detail history with score bars and latest matrix.
- Compare page with summary metrics and clearer regression sections.
- HTML error page for browser 404s while preserving JSON error responses for API callers.
- Accessible navigation, skip link, server-rendered `aria-current`, live status fragment and
  visible focus states.

## Screenshots

Before:

- `docs/assets/dashboard-redesign/before/dashboard-desktop.png`
- `docs/assets/dashboard-redesign/before/dashboard-mobile.png`
- `docs/assets/dashboard-redesign/before/run-detail-desktop.png`
- `docs/assets/dashboard-redesign/before/test-detail-desktop.png`

After:

- `docs/assets/dashboard-redesign/after/dashboard-desktop.png`
- `docs/assets/dashboard-redesign/after/dashboard-mobile.png`
- `docs/assets/dashboard-redesign/after/run-detail-desktop.png`
- `docs/assets/dashboard-redesign/after/test-detail-desktop.png`

## Validation

- `python -m compileall agentkit\web`
- `python -m pytest tests/test_web.py -q`
- `python -m pytest -q`
- `python -m ruff check agentkit/web tests/test_web.py`
- Desktop and mobile screenshots captured from `http://127.0.0.1:8766`.

Repo-wide `python -m ruff check .` still reports pre-existing issues outside this redesign scope in
`agentkit/core/schema.py`, `agentkit/reports/compliance.py` and `tests/test_security_p0.py`.
