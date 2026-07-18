 Here is Claude's plan:                                                                                               ↑
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ Productionizing agentkit — agent-executable task breakdown                                                           ↑
 ▎ First action on approval: copy this file to docs/plan.md in the repo. Everything                                   ↑
 ▎ below is written to be read by a Sonnet 5 agent that starts with no conversation
 ▎ context — each task is self-contained and cites its own files.                                                     ↑

 ---                                                                                                                  ↑
 Context
                                                                                                                      ↑
 agentkit is a correct single-operator tool: one process, one SQLite file, one packs
 directory, runs executed inline in the request handler. The goal is to serve a small set                             ↑
 of trusted design partners — each sees only their own agents, tests, and evidence —
 without over-building for scale that does not exist yet.                                                             ↑

 Seven blocking problems, all verified against the code:                                                              ↑

 1. Tenant content lives on the filesystem, globally. core/config.py:73 load_target(path) reads a YAML path; core/loader.py:159 discover(root) walks a
 directory; web/app.py:421 create_test writes to a shared packs/user/<id>.yaml.                                       ↑
 Partner A's authored test lands in the directory Partner B's discover() walks.
 Auth does not fix this — it is a data-model problem, and it is the most important item.                              ↑
 2. No ownership in the schema. core/store.py:15 _SCHEMA has no org column on
 agents, runs, test_results; every query is unscoped.                                                                 ↑
 3. Runs execute inside the HTTP handler. web/app.py:655 run_again calls run_tests
 synchronously — a 50-test pack at the 30s default timeout pins a uvicorn worker for                                  ↑
 minutes.
 4. Timeouts do not stop anything. core/runner.py:30 documents it: a timed-out                                        ↑
 agent.run keeps running, leaking a thread and socket per timeout, and runner.py:118
 discards the sandbox diff because the orphan may still be mutating it.                                               ↑
 5. Untrusted Python execution. core/loader.py:115 load_python_module calls
 exec_module, running top-level statements in-process as the server user.                                             ↑
 6. SSRF surface. config.py:34 HTTPSpec.endpoint is an arbitrary partner-supplied URL
 handed to httpx in core/agent.py. Hosted, a partner can point a target at                                            ↑
 169.254.169.254 and the worker fetches it from the worker's network position.
 7. Connection handling. web/app.py:90 get_store() opens a fresh sqlite3 connection                                   ↑
 per handler call and never closes it.
                                                                                                                      ↑
 Outcome: partners sign in as individual humans, see only their own data, and launch
 attributable runs that execute asynchronously and concurrently.                                                      ↑

 Decisions (rationale agents need; do not relitigate)                                                                 ↑

 - Postgres for concurrency, not scale. Multiple uvicorn workers writing SQLite gives                                 ↑
 "database is locked". Postgres also provides FOR UPDATE SKIP LOCKED — the whole queue.
 - No Redis, no Celery. A jobs table plus polling workers is a queue.                                                 ↑
 - No ORM, but strict migration discipline. store.py is 244 lines of plain SQL and
 the only DB access point in the repo. Versioning rules in T1.                                                        ↑
 - Keycloak for identity. Humans get OIDC; CI gets service accounts. No local
 users/memberships table — a second copy would drift.                                                                 ↑
 - Tenant test content becomes DB rows, not files. This is what delivers isolation and
 removes the RCE surface simultaneously.                                                                              ↑
 - Tenant-authored Python packs are not supported. First-party packs ship in the image,
 trusted by provenance. loader.py:115 never receives tenant input.                                                    ↑
 - Parallelism across runs now, within a run later. runner.py:239 builds one sandbox
 per run and resets it per test (runner.py:102), so concurrent runs share nothing;                                    ↑
 concurrent tests inside one run would race on that sandbox.
                                                                                                                      ↑
 Rejected: one deployment per partner (perfect isolation, zero tenancy code, but the
 ceiling is ~5–10 partners and it costs an N-way deploy per release).                                                 ↑

 Not building: Redis, HarnessBuild content-hash caching (app.py:439 _harness_view                                     ↑
 is a read model over a finished run — there is no generator to cache yet), a local
 users/memberships model, row-level security (per-connection SET app.tenant_id leaks                                  ↑
 across pooled connections — a subtler bug than it prevents), per-test parallelism,
 fine-grained roles, horizontal scaling.                                                                              ↑

 ---                                                                                                                  ↑
 Briefing — every agent must read this before starting
                                                                                                                      ↑
 Repo shape. The agentkit package is split across ./agentkit, ./backend, and
 ./frontend, reassembled by setuptools namespace packages. Import paths never contain                                 ↑
 backend or frontend — it is always from agentkit.core.store import Store.
                                                                                                                      ↑
 Commands. uv run is broken on Windows here — use python -m pytest. Full suite is
 ~174 tests, ~2.5s, so run it. Lint with python -m ruff check ., but repo-wide lint is                                ↑
 already red (~15 pre-existing violations, mostly import sorting) — never mistake a
 pre-existing violation for one you introduced; lint only the files you touched.                                      ↑

 Dependency direction — do not add a reverse edge.                                                                    ↑
 cli/web → core + reports + domains; reports → core; domains →
 core.sandbox; core imports nothing else from agentkit.                                                               ↑

 Hard invariants.                                                                                                     ↑
 - httpx is imported in exactly one file: backend/agentkit/core/agent.py.
 - SQLite/SQL is reached only through core/store.py:Store.                                                            ↑
 - Redaction runs twice on purpose — runner.py before building a TestResult, and
 store.py:save_run before the write. Removing either because "the other covers it"                                    ↑
 defeats the design.
 - runner.py must never raise; failures become Status.ERROR results.                                                  ↑
 - The import agentkit.domains.*.sandbox  # noqa: F401 lines in cli.py and web/app.py
 look dead and are not — they trigger @register_sandbox. Leave them.                                                  ↑

 Testing convention. One tests/test_<module>.py per module. Every new branch needs a                                  ↑
 test on the failure path, not just the happy path.
                                                                                                                      ↑
 Scope rule. Do not refactor code unrelated to your task. If your task appears to
 require changing core/schema.py, core/config.py's TargetConfig, or the assertion                                     ↑
 REGISTRY, stop and report — those are cross-cutting contracts and a change there
 belongs to a human.                                                                                                  ↑

 ---                                                                                                                  ↑
 Task graph
                                                                                                                      ↑
 T1 migrations infra ──┬─▶ T2 org_id + Store scoping ──┬─▶ T5 targets/packs tables ──┐
                       │                                ├─▶ T10 connection pool      │                                ↑
 T3 config refactor ───┴────────────────────────────────┤                            │
 T4 loader refactor ───────────────────────────────────┘                             │                                ↑
                                                                                      │
 T6 Keycloak infra ──▶ T7 JWT dependency ──▶ T8 scope all routes ◀────────────────────┘                               ↑
                                               └─▶ T9 delete FS test write
                                               └─▶ T14 artifact policy                                                ↑

 T2 ──▶ T11 jobs table ──▶ T12 worker ──┬─▶ T13 async POST /runs                                                      ↑
                                         └─▶ T15 secrets + egress
                                                                                                                      ↑
 T16 subprocess isolation — independent, any time
                                                                                                                      ↑
 Parallelizable immediately: T1, T3, T4, T6, T16 (five agents, no shared files).
 Then: T2 → {T5, T10}, T7. Then: T8 → {T9, T14}. Then: T11 → T12 → {T13, T15}.                                        ↑

 Human review required, do not merge from an agent unattended: T7, T15, T16.                                          ↑
 Security-sensitive or evidence-integrity code where a subtly wrong implementation passes
 tests and is still exploitable.                                                                                      ↑

 ---                                                                                                                  ↑
 Phase 1 — Tenancy in the data model
                                                                                                                      ↑
 T1 — Migration infrastructure
                                                                                                                      ↑
 Deps: none. Files: infra/migrations/, backend/agentkit/migrate.py, pyproject.toml.
                                                                                                                      ↑
 Create ordered raw-SQL migrations with real versioning. No Alembic, no ORM.
                                                                                                                      ↑
 - schema_migrations (version INT PRIMARY KEY, name TEXT, applied_at TIMESTAMPTZ).
 - Files at infra/migrations/NNNN_name.sql, applied in numeric order, recorded on apply.                              ↑
 - Each migration declares its rollback: either a paired NNNN_name.down.sql or a header
 comment stating it is irreversible and why. Column adds and new tables are reversible;                               ↑
 destructive backfills are not, and that must be visible before it runs.
 - A agentkit migrate console command applies pending migrations. Applied at deploy                                   ↑
 time by explicit command, never implicitly on app startup — two web replicas booting
 at once must not race.                                                                                               ↑
 - Migrations are forward-only in production; down files serve local dev and blast-radius
 reasoning.                                                                                                           ↑

 Acceptance: applying to an empty DB twice is idempotent; a partially-applied set                                     ↑
 resumes correctly; agentkit migrate --status lists pending.
 Validate: python -m pytest tests/test_migrate.py                                                                     ↑

 T2 — org_id on every row, Store scoping                                                                              ↑

 Deps: T1. Files: backend/agentkit/core/store.py, new migration, tests/test_store.py.                                 ↑

 The one-way door: retrofitting ownership later means backfilling rows whose owner you must                           ↑
 guess.
                                                                                                                      ↑
 - Add orgs (id, name, created_at); add org_id to agents, runs, test_results;
 index (org_id, started_at).                                                                                          ↑
 - Add org_id: str as a required leading parameter to every public method:
 save_run, list_agents, list_tests, list_runs, run_count, get_run,                                                    ↑
 pass_fail_matrix. Required, not defaulted — a forgotten argument must be a
 TypeError at test time, never a silent cross-tenant read. This is precisely why RLS is                               ↑
 unnecessary: one path to the data, guarded by the type system.
 - get_run(org_id, run_id) raises KeyError for another org's run — same response as                                   ↑
 not-found. Do not leak existence.
                                                                                                                      ↑
 Acceptance: a two-org fixture proves every read method returns only the calling org's
 rows; get_run on a foreign run raises KeyError; no method has a default org_id.                                      ↑
 Validate: python -m pytest tests/test_store.py then the full suite.
                                                                                                                      ↑
 T3 — Extract load_target_dict
                                                                                                                      ↑
 Deps: none (pure refactor, parallel-safe). Files: backend/agentkit/core/config.py, tests/test_config.py.
                                                                                                                      ↑
 Targets must be loadable from a DB row, not only a file path.
                                                                                                                      ↑
 - Add load_target_dict(raw: dict) -> TargetConfig containing the validation currently
 inlined in load_target: env interpolation (config.py:54), the sandbox check                                          ↑
 (config.py:95), the http-endpoint check (config.py:103).
 - load_target(path) becomes a thin file-reading wrapper over it. The CLI must be                                     ↑
 unchanged — this is a pure extraction, no behavior change.
 - Keep ${ENV_VAR} interpolation server-side; secrets never sit in stored config.                                     ↑

 Acceptance: load_target(path) and load_target_dict(yaml.safe_load(text)) produce                                     ↑
 identical TargetConfig objects for every fixture in agentkit/config/.
 Validate: python -m pytest tests/test_config.py tests/test_cli.py                                                    ↑

 T4 — Add load_tests_from_rows                                                                                        ↑

 Deps: none (pure refactor, parallel-safe). Files: backend/agentkit/core/loader.py, tests/test_loader.py.             ↑

 - Add load_tests_from_rows(rows: list[dict]) -> list[TestCase] reusing the existing                                  ↑
 _build_test_case (loader.py:59) verbatim. That function already enforces the
 assertion registry (loader.py:80), the category/risk enums, and the input xor                                        ↑
 turns rule — so DB-sourced tests get identical validation with no second code path.
 Do not write new validation.                                                                                         ↑
 - Leave discover() and load_python_module() untouched. They remain the
 first-party path used by the CLI and by packs shipped in the image.                                                  ↑

 Acceptance: a row-sourced TestCase equals the file-sourced one for identical                                         ↑
 content; an unknown assertion name in a row raises LoaderError exactly as from a file.
 Validate: python -m pytest tests/test_loader.py                                                                      ↑

 T5 — Targets and packs as DB rows                                                                                    ↑

 Deps: T2, T3, T4. Files: backend/agentkit/core/store.py, new migration, tests/test_store.py.                         ↑

 - targets (id, org_id, name, config_json, created_at) — a serialized TargetConfig.                                   ↑
 - packs (id, org_id, name, created_at), pack_tests (id, pack_id, test_json) — one
 serialized TestCase per row.                                                                                         ↑
 - CRUD on Store, all org_id-scoped per T2's convention.
 - Secrets are not in config_json. Store a secret_ref string; resolution is T15.                                      ↑
 Never persist a literal credential.
                                                                                                                      ↑
 Acceptance: a target round-trips through config_json → load_target_dict → an
 equal TargetConfig; a pack round-trips via load_tests_from_rows; cross-org reads                                     ↑
 return nothing.
 Validate: python -m pytest tests/test_store.py then the full suite.                                                  ↑

 ---                                                                                                                  ↑
 Phase 2 — Identity via Keycloak
                                                                                                                      ↑
 Ships before any external partner gets interactive access. A shared credential has no
 attribution on who launched a run, and revoking one person logs out the whole org. For a                             ↑
 tool whose output is evidence, unattributable actions defeat the product.
                                                                                                                      ↑
 T6 — Keycloak infrastructure and realm
                                                                                                                      ↑
 Deps: none (infra only, parallel-safe). Files: infra/docker-compose.yml, infra/keycloak/realm.json, docs/.
                                                                                                                      ↑
 - Keycloak service with its own database, separate from agentkit's.
 - One realm, one group per org. A protocol mapper puts the org into an org_id token                                  ↑
 claim. No local memberships table — Keycloak is the single source of truth for identity
 and org membership, so there is nothing to drift.                                                                    ↑
 - Humans: OIDC Authorization Code + PKCE. Keycloak owns sessions, reset, MFA, revocation.
 - CI/service access: Keycloak service accounts (client-credentials grant), one client                                ↑
 per partner. This replaces a hashed-API-key table entirely — same validation path, same
 claims, same revocation console.                                                                                     ↑
 - Realm config is version-controlled as exported realm JSON in infra/keycloak/, not
 clicked into the admin console. Auth config that exists only in a running container is                               ↑
 unreproducible and undiffable.
 - Keycloak is authoritative for identity and org membership only, not application                                    ↑
 authorization logic. Roles stay coarse (admin/viewer) or policy gets debugged in two
 places.                                                                                                              ↑

 Acceptance: docker compose up yields a realm importable from checked-in JSON; a test                                 ↑
 user in an org group receives a token carrying the org_id claim.
 Validate: manual — document the exact curl that fetches a token and shows the claim.                                 ↑

 T7 — JWT validation dependency  ⚠️ human review                                                                      ↑

 Deps: T6, T2. Files: frontend/agentkit/web/app.py, tests/test_web.py.                                                ↑

 - Replace the process-global _ACCESS_TOKEN / _require_token (app.py:42, app.py:60)                                   ↑
 with a dependency current_principal(request) -> (org_id, subject, email) validating the
 JWT against Keycloak's JWKS. Cache keys; refresh on unknown kid.                                                     ↑
 - org_id comes from the validated claim — never from a request parameter, path
 segment, or form field. This is the trust boundary.                                                                  ↑
 - Verify signature, exp, iss, and aud. A token failing any check is 401.
 - Do not stand up Keycloak in the test suite. Sign test tokens with a static test                                    ↑
 keypair.
                                                                                                                      ↑
 Acceptance: valid token → principal; expired, wrong-issuer, wrong-audience, and
 bad-signature tokens each → 401; an org_id supplied as a query parameter is ignored.                                 ↑
 Validate: python -m pytest tests/test_web.py
 Review: signature/claim validation that is subtly wrong passes tests and is still                                    ↑
 exploitable. A human reads this diff.
                                                                                                                      ↑
 T8 — Scope every route
                                                                                                                      ↑
 Deps: T7, T5. Files: frontend/agentkit/web/app.py, tests/test_web.py.
                                                                                                                      ↑
 - Apply current_principal to every route, not just state-changing ones — reads are
 the leak.                                                                                                            ↑
 - Pass org_id into every Store call. Because T2 made it required, a missed route fails
 loudly rather than serving another partner's data.                                                                   ↑
 - Record created_by (Keycloak sub, plus denormalized email for display) on runs and
 authored tests — the attribution a shared key could not provide.                                                     ↑

 Acceptance: every route 401s without a token; org B fetching org A's run id gets 404,                                ↑
 not 403; runs display who launched them.
 Validate: python -m pytest tests/test_web.py then the full suite.                                                    ↑

 T9 — Delete the filesystem test write                                                                                ↑

 Deps: T5, T8. Files: frontend/agentkit/web/app.py, tests/test_web.py.                                                ↑

 This closes the crosstalk hole. app.py:421 currently writes tenant-authored tests to                                 ↑
 get_packs_dir()/user/<id>.yaml — a directory every org's discover() walks.
                                                                                                                      ↑
 - Replace the file write with an insert into pack_tests scoped to the caller's org.
 - Keep the existing validation path (TestCase.model_validate and the                                                 ↑
 ASSERTION_REGISTRY check at app.py:418) — it is correct, only the sink changes.
 - /tests reads from pack_tests for the caller's org.                                                                 ↑

 Acceptance: a test authored by org A is invisible to org B in the UI and in the DB;                                  ↑
 no code path writes to packs/user/ anymore.
 Validate: python -m pytest tests/test_web.py                                                                         ↑

 T10 — Connection pool                                                                                                ↑

 Deps: T2. Files: frontend/agentkit/web/app.py, tests/test_web.py.                                                    ↑

 get_store() (app.py:90) opens a fresh connection per handler call and never closes it.                               ↑
 Replace with one pool created at app startup, handed to handlers via a dependency.
                                                                                                                      ↑
 Acceptance: connection count stays flat across many requests; no leaked handles.
 Validate: python -m pytest tests/test_web.py                                                                         ↑

 ---                                                                                                                  ↑
 Phase 3 — Asynchronous, concurrent runs
                                                                                                                      ↑
 T11 — Jobs table with lease fields
                                                                                                                      ↑
 Deps: T2. Files: new migration, backend/agentkit/core/store.py, tests/test_store.py.
                                                                                                                      ↑
 jobs (id, org_id, target_id, pack_id, state, run_id, created_by, error, priority, attempt_count, created_at, started_at, finished_at, lease_owner, lease_expires_at, heartbeat_at); state in queued|running|done|failed.          ↑

 Acceptance: claim/heartbeat/release/reclaim helpers exist on Store and are                                           ↑
 org-scoped for reads.
 Validate: python -m pytest tests/test_store.py                                                                       ↑

 T12 — Worker process                                                                                                 ↑

 Deps: T11. Files: backend/agentkit/worker.py (new), pyproject.toml, tests/test_worker.py.                            ↑

 - Loop: SELECT ... WHERE state='queued' ORDER BY priority, created_at FOR UPDATE SKIP LOCKED LIMIT 1, claim with lease_owner + lease_expires_at, run, persist.
 - Calls unchanged core.runner.run, then score, then store.save_run.                                                  ↑
 SKIP LOCKED means N workers need no coordination and no broker.
 - Real lease with heartbeat, not stale-started_at reclaim. The worker extends                                        ↑
 lease_expires_at on an interval well under the lease duration; a job is reclaimable
 only once that expires. This is what distinguishes a dead worker from a slow but                                     ↑
 healthy one — reclaiming on started_at alone cannot, so the timeout is either too
 short (duplicate execution of a live job) or too long (slow recovery).                                               ↑
 - Reclaim increments attempt_count; fail past a ceiling.
 - Retry infrastructure failures only. Never auto-retry an agent failure — runner.py                                  ↑
 turns those into Status.ERROR results, which are evidence, not errors.
 - Cap concurrent running jobs per org before dequeue so one partner cannot starve others.                            ↑

 Acceptance: two workers never double-claim; an expired lease is reclaimed; a                                         ↑
 heartbeating long job is not reclaimed; per-org cap holds.
 Validate: python -m pytest tests/test_worker.py                                                                      ↑

 T13 — Async submission and real status                                                                               ↑

 Deps: T12. Files: frontend/agentkit/web/app.py, templates, tests/test_web.py.                                        ↑

 - POST /runs (app.py:655) inserts a job and returns immediately; it no longer calls                                  ↑
 run_tests.
 - run_status (app.py:624) currently has dead branches — a persisted run always has                                   ↑
 finished_at, so running is never true. Repoint it at jobs for real state.
 - Reuse the existing _status_fragment.html + static/poll.js polling pattern that                                     ↑
 frontend/agentkit/web/CLAUDE.md prescribes. Do not invent a second mechanism.
                                                                                                                      ↑
 Acceptance: POST /runs returns without executing (job queued, no run row yet); the
 status endpoint reports genuine queued/running/done.                                                                 ↑
 Validate: python -m pytest tests/test_web.py
                                                                                                                      ↑
 T14 — Artifact storage policy
                                                                                                                      ↑
 Deps: T2, T8. Files: new migration, backend/agentkit/core/artifacts.py (new), frontend/agentkit/web/app.py.
                                                                                                                      ↑
 Decided now even though object storage is deferred: evidence blobs are where cross-tenant
 leakage reappears, because the first thing that writes a file inherits none of T2's                                  ↑
 scoping. Settle the rule before anything writes.
                                                                                                                      ↑
 - Structured evidence stays in Postgres, in test_results.result_json as today —
 already org-scoped, already redacted twice. Do not move it.                                                          ↑
 - Any blob (traces, screenshots, generated reports — none exist yet; app.py:595
 reports them "Unavailable") goes under a mandatory {org_id}/{run_id}/{artifact_id}                                   ↑
 prefix, with metadata in artifacts (id, org_id, run_id, kind, size, path, created_at).
 - No component constructs an artifact path itself. One helper in core/ owns path                                     ↑
 construction and takes org_id as a required argument — the same guard as Store.
 - Serve artifacts only through an authenticated route checking the row's org_id against                              ↑
 the token claim. Never as static files.
 - Because the prefix is fixed from day one, swapping in object storage later is a backend                            ↑
 change, not a migration.
                                                                                                                      ↑
 Acceptance: the path helper cannot produce a path without an org_id; an artifact of
 org A is 404 with an org B token; no static mount exposes the artifacts root.                                        ↑
 Validate: python -m pytest tests/test_artifacts.py tests/test_web.py
                                                                                                                      ↑
 T15 — Secret resolution and egress allowlist  ⚠️ human review
                                                                                                                      ↑
 Deps: T12. Files: backend/agentkit/worker.py, backend/agentkit/core/agent.py, tests/test_security_p0.py.
                                                                                                                      ↑
 Secrets:
 - secret_ref resolves in the worker, at run start, for that run only. The resolved                                   ↑
 value goes to the subprocess environment and is never written to config_json, logs,
 the jobs table, or evidence. The existing Redactor stays the last line of defense, not                               ↑
 the first.
 - Prefer short-lived credentials; where the partner's system cannot issue them, scope the                            ↑
 long-lived secret to the single target.
                                                                                                                      ↑
 Egress — this closes an SSRF hole, not a hardening nice-to-have:
 - HTTPSpec.endpoint (config.py:34) is partner-supplied and handed to httpx, so an                                    ↑
 unrestricted worker is an SSRF primitive.
 - Store a host allowlist on the target; validate the resolved endpoint at run start.                                 ↑
 - Block link-local, loopback, and private ranges by default — after DNS resolution, so
 a hostname resolving to 169.254.169.254 is rejected. Validating the string alone is                                  ↑
 insufficient and is the usual way this is gotten wrong.
 - Run workers in a network segment with no reach to the control-plane database or the                                ↑
 cloud metadata endpoint.
                                                                                                                      ↑
 Acceptance: a target pointing at 169.254.169.254 is rejected before any request; a
 hostname resolving to a private address is likewise rejected; a resolved secret appears in                           ↑
 no log, table, or evidence payload.
 Validate: python -m pytest tests/test_security_p0.py tests/test_redaction.py                                         ↑
 Review: DNS-rebinding and allowlist bypasses pass naive tests. A human reads this diff.
                                                                                                                      ↑
 ---
 Phase 4 — Killable run isolation                                                                                     ↑

 T16 — Subprocess execution  ⚠️ human review                                                                          ↑

 Deps: none — ungated, a correctness fix worth shipping single-tenant.                                                ↑
 Files: backend/agentkit/core/runner.py, tests/test_runner.py.
                                                                                                                      ↑
 runner.py:30 documents the defect: _run_with_timeout submits to a ThreadPoolExecutor
 and abandons the thread on timeout, because CPython has no thread-kill primitive. A hung                             ↑
 agent leaks a thread and socket per timeout, and runner.py:118 must discard the sandbox
 diff since the orphan may still be mutating it — so a timed-out test yields no usable                                ↑
 evidence.
                                                                                                                      ↑
 - Execute each run in a subprocess; enforce the timeout by killing the process tree.
 ProcessPoolExecutor or plain subprocess with a RunResult over a pipe. No container                                   ↑
 runtime at this scale.
 - With a killable worker the timeout path can trust sandbox state again — replace the                                ↑
 diff = None branch at runner.py:126 with a real diff, and delete the ponytail comment
 at runner.py:33 along with the leak it describes.                                                                    ↑
 - Set CPU, memory, and wall-time ceilings on the child.
 - runner.py must still never raise — subprocess crashes become Status.ERROR.                                         ↑

 Acceptance: an agent sleeping past its timeout is reaped (no orphan process), the                                    ↑
 result carries a trustworthy diff, and no exception escapes run().
 Validate: python -m pytest tests/test_runner.py then the full suite.                                                 ↑
 Review: this changes what counts as trustworthy evidence. A human reads this diff.
                                                                                                                      ↑
 ---
 Phase 5 — Deployment                                                                                                 ↑

 T17 — Compose, network policy, cutover                                                                               ↑

 Deps: T13, T15. Files: infra/docker-compose.yml, infra/Dockerfile, docs/.                                            ↑

 - Postgres and Keycloak (own DB) in compose. Migrations by explicit deploy step (T1).                                ↑
 - Web and worker as separate services from the same image, differing only in command, on
 different network policies: only web reaches Keycloak's public endpoints; only the                                   ↑
 worker reaches partner endpoints; the worker does not reach the control-plane DB
 directly if avoidable.                                                                                               ↑
 - AGENTKIT_DB becomes a Postgres DSN. Keep SQLite for local dev and the test suite while
 it stays free; drop it the moment it costs branches in store.py.                                                     ↑
 - Bind 0.0.0.0 only behind TLS and T7's dependency. The 127.0.0.1 default in
 .claude/rules/security-sensitive.md exists because the run endpoint executes packs —                                 ↑
 that reasoning retires only once tenant packs are YAML-only (T5/T9) and every route is
 authenticated (T8). Not before.                                                                                      ↑

 ---                                                                                                                  ↑
 End-to-end verification (after the phases land)
                                                                                                                      ↑
 1. python -m pytest — full suite, ~4s. bash tools/validate.sh before declaring done.
 2. Two-org: two Keycloak users in different org groups; author a test as A, run it;                                  ↑
 confirm B's /tests, /runs, /agents are empty, B fetching A's run id returns 404,                                     ↑
 and the run records A's user as created_by.
 3. Revocation: disable user A in Keycloak; their session stops working, the org's other
ers are unaffected.
 4. Concurrency: enqueue several runs, start two workers; both progress, no job is
 double-claimed, and killing one worker mid-run lets the other reclaim only after lease
 expiry.
 5. Isolation: point a target at a hanging agent; the run times out, the child is
 reaped, and a usable sandbox diff is still recorded.
 6. Egress: targets at 169.254.169.254 and at a hostname resolving to a private
 address are both rejected before any request.
 7. Regression canary: agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml still works unchanged — the CLI's file-based path
 proves T3/T4/T5 did not break first-party packs.
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
                                                                                                                         ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Claude has written up a plan and is ready to execute. Would you like to proceed?                                   
 ❯ 1. Yes, and use auto mode
   2. Yes, manually approve edits                                                                                          3. No, refine with Ultraplan on Claude Code on the web                                                             4. Tell Claude what to change
      shift+tab to approve with this feedback
                                                                                                                    ctrl+g to edit in Notepad · ~\.claude\plans\t

---

## Amendment (2026-07-18) — T1 uses Alembic, not hand-rolled raw SQL

Original T1 decided against Alembic/ORM ("No ORM, but strict migration discipline" /
"Create ordered raw-SQL migrations with real versioning. No Alembic, no ORM."). The user
explicitly overrode this during implementation and asked for Alembic instead.

**What actually shipped for T1:**

- Alembic + SQLAlchemy added as dependencies (`pyproject.toml`) — used only as migration
  tooling. `alembic` and `sqlalchemy` are required transitively for the migration runner;
  they are not imported anywhere else in the codebase.
- `store.py` is untouched and still the only runtime DB access point, still plain `sqlite3`.
  Alembic drives schema evolution; it does not become a second way to read/write app data.
- Layout: `alembic.ini` (repo root) → `script_location = infra/alembic`;
  `infra/alembic/env.py` (raw-SQL env, `target_metadata = None`, no ORM models). The
  migration package is included in built wheels, and the application resolves the
  script directory through package resources rather than assuming a source checkout;
  `infra/alembic/versions/0001_baseline_schema.py` (the same `agents`/`runs`/`test_results`
  schema `Store` already creates, via `op.execute("CREATE TABLE IF NOT EXISTS ...")`, so it
  is idempotent against a DB `Store` already initialized directly).
- `agentkit migrate [--db PATH] [--status]` — new CLI subcommand
  (`backend/agentkit/cli.py`) wrapping `alembic.command.upgrade`, with `sqlalchemy.url` set
  dynamically from `--db` per invocation. Status lists pending revisions in application
  order, or reports that the database is up to date.
- The old `infra/migrations/*.sql` (custom raw-SQL engine) and `backend/agentkit/migrate.py`
  (hand-rolled runner) built earlier in this session were deleted in favor of the above.
- Tests: `tests/test_migrate.py` — applies cleanly to a fresh DB, is idempotent on a second
  invoke, resumes from a partially-created baseline, and verifies pending/up-to-date status
  output as well as the `alembic_version` table.

Future tasks that touch migrations (T2, T5, T11, T14 — anywhere the plan says "new
migration") should add an Alembic revision under `infra/alembic/versions/` via
`alembic revision -m "<name>"` (or by hand, following `0001_baseline_schema.py`'s pattern),
not a new `infra/migrations/NNNN_name.sql` file — that directory no longer exists.
