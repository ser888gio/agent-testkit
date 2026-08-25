# `agentaudit.web` — FastAPI JSON API + React dashboard

Imported as `agentaudit.web.*`. Served by `agentaudit ui` / `bash infra/dev.sh`.

## Entry points

- `app.py` — the FastAPI app: OIDC auth routes, mounts (`/static`, `/assets`),
  and the SPA catch-all. Holds routing, not derivation.
- `api.py` — the JSON API under `/api/*`. The React SPA's only data source.
  Each endpoint returns the same derivation a page used to render, via
  `core/runview.py`.
- `runtime.py` — process-wide state: the long-lived `Store`, path resolution
  (`resolve_within_allowed`), packs/artifacts dirs, first-party import.
  Shared by `app.py` and `api.py`; do not let them import each other.
- `auth.py` — OIDC, sessions, `Principal`, CSRF for session mutations.
- The pages themselves live in `frontend/spa` (React 18 + TypeScript + Vite +
  react-router). Build with `npm ci && npm run build` there; output lands in
  `spa_dist/` and is served by `app.py`.

## Constraints

- **Read-mostly control plane.** This app consumes `RunResult`/`ScoreReport`
  from `Store`. The one exception is run enqueue, which queues work the worker
  executes (and imports shipped target/pack rows). Do not add further paths
  that call agents directly; discovery only ever *queues* a job.
- **Every application route takes a `Principal`.** Reads included, since reads
  are the leak — this includes the SPA shell catch-all in `app.py`. Pass
  `principal.org_id` into every `Store` call. Only `/login`,
  `/auth/callback`, and `/logout` are public. Mutations depend on
  `require_admin`, which enforces CSRF for browser sessions (the SPA echoes
  the token from `/api/session` via `x-csrf-token`).
  `tests/test_web.py::test_every_route_requires_a_token` walks the route table,
  so a route that forgets this fails the suite.
- **This app writes no files.** Tenant-authored tests are rows in `pack_tests`,
  scoped to the caller's org. `test_no_code_path_writes_to_packs_user_dir`
  enforces the absence of `write_text`/`mkdir` in `app.py`/`api.py`/`runtime.py`.
- **Never render unredacted evidence.** Everything reaching the API has already
  passed through the `Redactor` on the way into the store. Do not add a route
  that bypasses `Store` to read raw data.
- **Binds `127.0.0.1` by default, and that default matters.** Run enqueue can
  load target/pack files and execute Python test modules under the packs
  directory; paths are validated by `runtime.resolve_within_allowed`. Any
  change that widens the default bind, accepts a user-supplied path, or relaxes
  path validation is security-sensitive — see `.claude/rules/security-sensitive.md`.
- **Derivation stays in `core/runview.py`** (`dashboard`, `library`, `detail`,
  `harness`). API handlers read query params, call one of those, serialize.
  Put new derivation there, where it is testable without a `TestClient`.
- **SPA markup lives in `frontend/spa/src`.** `data-testid` hooks are asserted
  by `tests/test_web.py::test_spa_source_keeps_nav_and_action_hooks` — keep
  them stable when renaming. No `innerHTML`/`dangerouslySetInnerHTML` anywhere
  (also asserted).
- Route order matters in `api.py`: literal segments like
  `/agents/register-options` must be declared before the
  `/agents/{agent_id:path}` catch-all.

## Testing expectations

`tests/test_web.py` drives the JSON API through Starlette's `TestClient`. Every
new route needs a test covering at least the happy path and the not-found path;
markup-level assertions go against the SPA sources, not rendered HTML. After
changing SPA code, rebuild (`npm run build`) before manual verification with
`bash infra/dev.sh` — TestClient never executes JavaScript.

Validation: `uv run python -m pytest tests/test_web.py tests/test_security_p0.py`,
plus `npm run build` in `frontend/spa` for SPA changes.

Spec: [`docs/specs/web-ui.md`](../../../docs/specs/web-ui.md).
