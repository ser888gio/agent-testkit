# PRD-005: Presentation Readiness

**Type:** Fix / Hygiene · **Priority:** 5 (cheap, unblocks public-facing work)

## Problem

The repository's hygiene is better than a first audit suggested — build
artifacts (`build/`, `dist/`, `*.db`, `.ruff_cache`) are correctly gitignored,
and CI workflows exist (`.github/workflows/ci.yml`, `security.yml`). However,
verification surfaced four concrete credibility problems that matter exactly
when the product is being demoed, pitched, or installed by a new user:

1. **Shipped wheels have no dashboard.** The CI `package` job runs only
   `uv build`; there is no Node step. Because
   `frontend/agentaudit/web/spa_dist/` is gitignored, a CI checkout has an
   empty bundle, so every published wheel serves `_SPA_PLACEHOLDER`
   ("dashboard not built yet") from `app.py` forever. Local dev works and
   hides this completely.
2. **No runnable examples.** The `examples/` directory was deliberately
   removed (`README.md:228-229`); new users must reverse-engineer target YAML
   and pack structure from source.
3. **Docs actively contradict each other.** `AGENTS.md:5`, root `CLAUDE.md`,
   and `docs/project-map.md` still describe "the FastAPI/React dashboard" —
   the dashboard was rewritten in React (commit `fd13da3`). `CONTRIBUTING.md` claims "`uv run` is currently
   broken on Windows", "repo-wide lint is red", and "~190s suite", while
   `tools/validate.sh` states the opposite ("repo lints clean", ~4s suite)
   and is authoritative today.
4. **No scripted demo.** Nothing walks a newcomer through the money moment:
   an agent failing a side-effect assertion, visible evidence, compliance
   report.

## Evidence

- `.github/workflows/ci.yml` `package` job: checkout → setup-uv → `uv build`.
  No Node/npm step anywhere in that job (verified 2026-08-26 at commit `e4cfe48`).
- `pyproject.toml:71-72` declares package-data `spa_dist/*`; `.gitignore`
  ignores `frontend/agentaudit/web/spa_dist/`.
- `frontend/spa/package.json` has no test runner; nothing in CI compiles or
  verifies the SPA except the docs job (which builds the *website*, not the SPA).
- Grep confirms zero `templates/` under `frontend/agentaudit/web/`.

## Goals

1. **Wheels ship a working dashboard**: the `package` job builds the SPA
   (`npm ci && npm run build` in `frontend/spa`) before `uv build`, plus a
   packaging smoke check asserting `spa_dist/index.html` lands in the wheel.
2. Restore `examples/` with three copy-paste quickstarts: zero-config HTTP
   endpoint run; treasury unsafe-agent demo proving side-effect detection;
   `--external` promptfoo/garak integration.
3. Reconcile stale docs: update AGENTS.md, CLAUDE.md, docs/project-map.md to
   describe the JSON API + React SPA split; align CONTRIBUTING.md with
   tools/validate.sh reality; resolve the MCP contradiction between
   `docs/plan-competitive-response.md` ("not doing MCP") and
   `docs/prds/README.md` (MCP = priority 1).
4. Add `docs/demo.md`: a 5-minute scripted walkthrough (`run` → inspect
   failing split-payment evasion evidence in the dashboard → `compare` →
   `report --format compliance`) with expected output at each step.

## Non-goals

- Removing artifacts from git history (they were never tracked — nothing to purge).
- Any behavior change to package code beyond CI/packaging steps.

## Requirements

1. Packaging fix verified mechanically: after CI-equivalent local steps
   (`npm ci && npm run build` then `uv build`), inspect `dist/*.whl` and assert
   a `spa_dist/index.html` entry exists.
2. Examples import only shipped surfaces (`agentaudit.*`, never
   `backend.agentaudit.*`) and are exercised by a smoke test
   (`tests/test_examples.py`) so they cannot rot.
3. Every doc claim changed is verified once against reality before the edit
   (run `ruff check .`; time the suite; run the example).
4. Demo script executed end to end once before merge.

## Success metrics

- Fresh clone → CI `package` job → wheel contains dashboard assets; pip
  install of that wheel → `agentaudit ui` renders the real SPA.
- Fresh clone → each example command runs unmodified (Windows + POSIX).
- Zero contradictions remain between CONTRIBUTING.md, AGENTS.md,
  CLAUDE.md, and tools/validate.sh (manual review checklist in PR).
- Demo completes in < 5 minutes including screenshot steps.

## Open questions

- Should the wheel also gain a minimal fallback page when `spa_dist` is absent
  (clear error instead of placeholder)? Recommend yes as a follow-up.
- Where demo screenshots/GIFs live if added later.
