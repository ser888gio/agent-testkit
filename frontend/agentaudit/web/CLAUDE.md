# `agentaudit.web` — FastAPI dashboard

Imported as `agentaudit.web.*`. Served by `agentaudit ui` / `bash infra/dev.sh`.

## Entry points

- `app.py` — the whole application: route handlers, run-harness endpoints, and the
  `Store` queries that feed them. Templates in `templates/`, assets in `static/`.
- `/generated` — the review queue for machine-authored tests. Promotion mutates the
  audited baseline, so it is `require_admin` + CSRF like every other mutation. The id
  rewrite lives in `core/evolve.py:promoted_id`, not here.
- `templates/base.html` + `_components.html` — shared layout and partials; new pages should
  extend/include these rather than restating markup.
- `_status_fragment.html` + `static/poll.js` — the polling pattern used for in-progress runs.
  Reuse it for any new async status surface instead of inventing a second mechanism.

## Constraints

- **Read-mostly control plane.** This app consumes `RunResult`/`ScoreReport` from `Store`.
  The one exception is the re-run endpoint, which invokes `core.runner.run`. Do not add
  further paths that call agents directly.
- **Every application route takes a `Principal`.** Add
  `principal: Principal = Depends(current_principal)` to any new application route — reads
  included, since reads are the leak — and pass
  `principal.org_id` into every `Store` call. `DEFAULT_ORG` is deliberately not imported
  here. Only the OIDC `/login`, `/auth/callback`, and `/logout` protocol endpoints are public.
  Mutations depend on `require_admin`, which also enforces CSRF for browser sessions.
  `tests/test_web.py::test_every_route_requires_a_token` walks the route table, so a route that
  forgets this fails the suite.
- **This app writes no files.** Tenant-authored tests are rows in `pack_tests`, scoped to the
  caller's org; the packs directory is shared and every org's `discover()` walks all of it.
  `test_no_code_path_writes_to_packs_user_dir` enforces the absence of `write_text`/`mkdir`.
- **Never render unredacted evidence.** Everything reaching a template has already passed
  through the `Redactor` on the way into the store. Do not add a route that bypasses `Store`
  to read raw data.
- **Binds `127.0.0.1` by default, and that default matters.** The re-run endpoint can load
  target/pack files and execute Python test modules under the packs directory. Any change
  that widens the default bind, accepts a user-supplied path, or relaxes path validation is
  security-sensitive — see `.claude/rules/security-sensitive.md`.
- **`app.py` is ~700 lines.** Prefer pushing new logic into `core/` where it is testable
  without a `TestClient`, rather than growing this file.
- Sandbox registration is import-triggered: the `agentaudit.domains.*.sandbox`
  `# noqa: F401` imports at the top of `app.py` are load-bearing. Do not "clean up" them.

## Testing expectations

`tests/test_web.py` drives routes through Starlette's `TestClient`. Every new route needs a
test there covering at least the happy path and the not-found/error path (`error.html`
exists for a reason).

Validation: `python -m pytest tests/test_web.py`, then load the page manually with
`bash infra/dev.sh` for template changes — the test client will not catch broken CSS or
a Jinja block that renders empty.

Spec: [`docs/specs/web-ui.md`](../../../docs/specs/web-ui.md).
