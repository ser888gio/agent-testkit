# Advisory Audit — agentaudit @ commit `e4cfe48` (2026-08-26)

Read-only audit produced with the `improve` skill methodology: recon +
four parallel category auditors (correctness/security/tests+DX+docs/debt+deps+
direction), followed by advisor verification of every planned finding against
the live code. Executable handoff plans live in [`plans/`](../../plans/README.md).

## Vetted findings (ordered by leverage)

| # | Finding | Category | Impact | Effort | Risk | Confidence | Evidence |
|---|---------|----------|--------|--------|------|------------|----------|
| 1 | Backslash-form open redirect in OIDC login `next` url (`/\evil.com` passes validation) | security | Phishing hop inheriting IdP trust post-login | S | LOW | HIGH (verified) | `web/auth.py:252-257`, redirect at `web/app.py:102-107` |
| 2 | CI wheels ship without the SPA bundle → `agentaudit ui` broken for pip consumers | dx | Product appears broken to every wheel consumer; hidden locally | S | LOW | HIGH (verified) | `ci.yml` package job; gitignored `spa_dist` |
| 3 | Worker keeps auditing after losing its lease → duplicate runs, double attack traffic vs live endpoints | bug | Duplicate evidence rows; concurrent dialing of partner endpoints | S | LOW | HIGH (verified) | `worker.py:68-74` heartbeat returns silently; `should_stop` checks only cancel flag |
| 4 | Cancel-vs-done race in `work_once`: cancellation can be recorded as a passing gate decision | bug | Lost user cancels; wrong gate verdicts | S | LOW | HIGH | `worker.py:321-326` check-then-act |
| 5 | Route-table auth walk silently degrades on unknown path params | tests | The suite property guaranteeing "every route needs a Principal" can silently stop covering new routes | S | LOW | HIGH (verified) | `tests/test_web.py:683-709` hardcoded substitutions |
| 6 | Dashboard lacks `frame-ancestors`/`X-Frame-Options` | security | Clickjacking an admin session supplies valid CSRF tokens | S | LOW | HIGH | no middleware in `app.py` construction |
| 7 | Authenticated API responses lack `Cache-Control: no-store` | security | Session token/evidence cacheable by intermediaries on hosted deploys | S | LOW | MED | `api.py` routes, no header middleware anywhere |
| 8 | Hanging sandbox RPC handler stalls turn budget past deadline | bug | One wedged tool call consumes whole-test budget; inflated latency evidence | M | MED | HIGH | `isolation.py:455-490` unbounded `_handle_rpc` |
| 9 | Timed-out agent threads leak on the direct-runner path | bug | Thread/socket accumulation across repeated timeouts | S | LOW | HIGH | `runner.py:46-55` abandoned executor threads |
| 10 | `/logout` destroys session via unauthenticated GET | security | Forced-logout CSRF nuisance; loses unsaved review work | S | LOW | HIGH | `app.py:120-125` |
| 11 | Viewer-visible `/api/settings` leaks server paths + egress escape-hatch flag | security | Recon surface for multi-tenant deployments | S | LOW | MED | `api.py:845-869` |
| 12 | `record_progress` read-modify-write loses entries under concurrency | bug | Dashboard live-progress drops/double-counts tests | S | LOW | HIGH | `store.py:522-540` |
| 13 | SPA session fetch has no error state → eternal spinner on non-401 failure | bug | Backend blip bricks tab until manual reload | S | LOW | HIGH | `frontend/spa/src/session.tsx:20-26` |
| 14 | React SPA has zero test infrastructure; `tools/affected.sh` maps SPA changes to zero tests | tests | 17 TSX pages ship untested; regressions found by clicking | M | LOW | HIGH | `frontend/spa/package.json` scripts |
| 15 | No Python typechecker; SPA `tsc` never runs in any pipeline | dx | Type drift lands as runtime failures | M/S | MED/LOW | HIGH | pyproject has ruff only; ci.yml has no tsc |
| 16 | `Store.delete_target` implemented + tested but unreachable (no route/CLI) | tech-debt | Create-without-delete asymmetry; dead tested code | S | LOW | HIGH | `store.py:803` vs full api/cli inventory |
| 17 | Docs contradict reality: Jinja-era references (AGENTS.md:5, CLAUDE.md, project-map.md); CONTRIBUTING.md vs validate.sh; MCP do/don't contradiction across planning docs | docs | Agents/contributors steered at templates that don't exist; contradictory strategy signals | S | LOW | HIGH | see PRD-005 |
| 18 | `core/store.py` (56KB) and `core/isolation.py` (31KB) are god-modules mixing concerns | tech-debt | Trust-sensitive containment path edited under generic review attention | M/L | MED–HIGH | HIGH | store.py:293/391/664 seams; isolation.py three concerns |
| 19 | Version pinning inconsistent in pyproject.toml (three exact floors, rest floorless) | deps | Unlocked installs drift; policy unclear | S | LOW | HIGH | pyproject.toml:12-24 |

## Direction findings (maintainer options, separately weighed)

1. **Merge the stranded `feat/sarif-export` branch** (`cbf133e`) — complete,
   tested SARIF 2.1.0 export matching `docs/plan-competitive-response.md`
   Task 3; makes ASI mapping visible in GitHub Security tab. Effort S.
2. **DeepEval adapter** — the adapter seam (`ExternalEvalAdapter` ABC,
   registry, dispatch) requires zero changes for a third adapter; PRD-002
   covers the spec. Effort M.
3. **Incident→regression import loop** — surface asymmetry (evidence exports,
   nothing ingests); reuses evolve review queue end-to-end; PRD-003. Effort M–L.
4. **Surface dormant model-driven features** (attacker/judge/evolve env-gated
   and invisible through the dashboard) — read-only capability probe +
   settings surfacing first. Effort M, maintainer's call given fail-closed philosophy.
5. **Re-baseline roadmap status tables** — `project-map.md` marks W3/W4
   execution as missing though `core/audit.py:45-79` now executes external
   adapters; resolve MCP contradiction before choosing Wave 2/3 work.

## Considered and rejected (do not re-audit)

- **Committed build/dist/db artifacts**: initial report claimed committed;
  disproved — all gitignored, zero tracked files. (Fixed PRD-005 accordingly.)
- **Missing CI workflows**: initial report claimed none exist;
  `.github/workflows/ci.yml` + `security.yml` are present and substantive.
- **`reclaim` UPDATE parameter mismatch suspicion** (`store.py:627-637`):
  binds correctly on inspection.
- **Windows Job Object cleanup** (`isolation.py`): kill-on-close semantics
  verified sound; raises loudly if attach fails.
- **Honoring proxy env vars / argv-list subprocess spawning / parameterized
  SQL f-string fragments**: by-design per playbook rule, reviewed explicitly.
