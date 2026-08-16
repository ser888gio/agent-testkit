# Productionizing AgentKit

Agent-executable task breakdown for serving a small set of trusted design partners.

This plan is written for agents that start with no conversation context. Each task is self-contained and cites the files it expects to touch.

## Context

`agentkit` is currently a correct single-operator tool: one process, one SQLite file, one packs directory, with runs executed inline in the request handler.

The goal is to serve a small set of trusted design partners. Each partner must see only their own agents, tests, and evidence, without over-building for scale that does not exist yet.

### Blocking Problems

1. **Tenant content lives on the filesystem globally.**
   `core/config.py:73` `load_target(path)` reads a YAML path; `core/loader.py:159` `discover(root)` walks a directory; `web/app.py:421` `create_test` writes to shared `packs/user/<id>.yaml`. Partner A's authored test lands in the directory Partner B's `discover()` walks. Auth does not fix this; it is a data-model problem.

2. **No ownership in the schema.**
   `core/store.py:15` `_SCHEMA` has no `org` column on `agents`, `runs`, or `test_results`; every query is unscoped.

3. **Runs execute inside the HTTP handler.**
   `web/app.py:655` `run_again` calls `run_tests` synchronously. A 50-test pack at the 30s default timeout pins a uvicorn worker for minutes.

4. **Timeouts do not stop anything.**
   `core/runner.py:30` documents that a timed-out `agent.run` keeps running, leaking a thread and socket per timeout. `runner.py:118` discards the sandbox diff because the orphan may still be mutating it.

5. **Untrusted Python execution.**
   `core/loader.py:115` `load_python_module` calls `exec_module`, running top-level statements in-process as the server user.

6. **SSRF surface.**
   `config.py:34` `HTTPSpec.endpoint` is an arbitrary partner-supplied URL handed to `httpx` in `core/agent.py`. Hosted, a partner can point a target at `169.254.169.254` and the worker fetches it from the worker's network position.

7. **Connection handling.**
   `web/app.py:90` `get_store()` opens a fresh SQLite connection per handler call and never closes it.

### Outcome

Partners sign in as individual humans, see only their own data, and launch attributable runs that execute asynchronously and concurrently.

## Decisions

Do not relitigate these unless new product or security constraints arrive.

- Use Postgres for concurrency, not scale. Multiple uvicorn workers writing SQLite gives `database is locked`. Postgres also provides `FOR UPDATE SKIP LOCKED`, which is enough for the queue.
- Do not use Redis or Celery. A jobs table plus polling workers is a queue.
- Use Keycloak for identity. Humans get OIDC; CI gets service accounts. Do not build a local users/memberships table that can drift.
- Tenant test content becomes DB rows, not files. This delivers isolation and removes the RCE surface.
- Tenant-authored Python packs are not supported. First-party packs ship in the image, trusted by provenance. `loader.py:115` must never receive tenant input.
- Parallelize across runs now, within a run later. `runner.py:239` builds one sandbox per run and resets it per test (`runner.py:102`), so concurrent runs share nothing. Concurrent tests inside one run would race on that sandbox.
- Migration tooling now uses Alembic. See the amendment at the end of this document for the implemented T1 decision.

### Rejected

- One deployment per partner. It gives perfect isolation and zero tenancy code, but the ceiling is about 5-10 partners and it costs an N-way deploy per release.

### Not Building

- Redis
- HarnessBuild content-hash caching
- Local users/memberships model
- Row-level security
- Per-test parallelism
- Fine-grained roles
- Horizontal scaling

`app.py:439` `_harness_view` is a read model over a finished run; there is no generator to cache yet. Row-level security is rejected because per-connection `SET app.tenant_id` can leak across pooled connections, creating a subtler bug than it prevents.

## Briefing

Every agent must read this before starting.

### Repo Shape

The `agentkit` package is split across `./agentkit`, `./backend`, and `./frontend`, then reassembled by setuptools namespace packages. Import paths never contain `backend` or `frontend`; use imports such as:

```python
from agentkit.core.store import Store
```

### Commands

On Windows, call pytest as a module rather than a console script (`uv run ... pytest` hits a
trampoline error; `python -m pytest` and `uv run ... python -m pytest` both work):

```powershell
python -m pytest
```

The full suite is 493 tests and about 150 seconds, so prefer `bash tools/validate.sh
--affected` while iterating and run the full suite before declaring done.

Lint with:

```powershell
python -m ruff check .
```

Lint is green and CI enforces it, so any violation you see is one your change introduced.

### Dependency Direction

Do not add a reverse edge:

```text
cli/web -> core + reports + domains
reports -> core
domains -> core.sandbox
core -> nothing else from agentkit
```

### Hard Invariants

- `httpx` is imported in exactly one file: `backend/agentkit/core/agent.py`.
- SQLite/SQL is reached only through `core/store.py:Store`.
- Redaction runs twice on purpose: `runner.py` before building a `TestResult`, and `store.py:save_run` before the write. Removing either because "the other covers it" defeats the design.
- `runner.py` must never raise; failures become `Status.ERROR` results.
- The `import agentkit.domains.*.sandbox  # noqa: F401` lines in `cli.py` and `web/app.py` look dead and are not; they trigger `@register_sandbox`. Leave them.

### Testing Convention

Use one `tests/test_<module>.py` per module. Every new branch needs a test on the failure path, not just the happy path.

### Scope Rule

Do not refactor code unrelated to your task.

If your task appears to require changing `core/schema.py`, `core/config.py`'s `TargetConfig`, or the assertion `REGISTRY`, stop and report. Those are cross-cutting contracts and a change there belongs to a human.

## Task Graph

```text
T1 migrations infra -> T2 org_id + Store scoping -> T5 targets/packs tables
                                                 -> T10 connection pool

T3 config refactor -> T5 targets/packs tables
T4 loader refactor -> T5 targets/packs tables

T6 Keycloak infra -> T7 JWT dependency -> T8 scope all routes -> T9 delete FS test write
                                                        -> T14 artifact policy

T2 -> T11 jobs table -> T12 worker -> T13 async POST /runs
                                  -> T15 secrets + egress

T16 subprocess isolation: independent, any time
```

Parallelizable immediately: T1, T3, T4, T6, T16.

Then: T2 -> T5 and T10; T7. Then: T8 -> T9 and T14. Then: T11 -> T12 -> T13 and T15.

Human review required: T7, T15, T16. These touch security-sensitive or evidence-integrity code where a subtly wrong implementation can pass tests and still be exploitable.

## Phase 1: Tenancy in the Data Model

### T1: Migration Infrastructure - Done

**Status:** Superseded by the Alembic amendment at the end of this document.

**Original dependencies:** none
**Original files:** `infra/migrations/`, `backend/agentkit/migrate.py`, `pyproject.toml`

The original plan called for ordered raw-SQL migrations with custom versioning and no Alembic. That decision was explicitly overridden during implementation. Use Alembic revisions under `infra/alembic/versions/` for future migration work.

### T2: `org_id` on Every Row, Store Scoping - Done

**Dependencies:** T1
**Files:** `backend/agentkit/core/store.py`, new migration, `tests/test_store.py`

Retrofitting ownership later means backfilling rows whose owner must be guessed.

- Add `orgs (id, name, created_at)`.
- Add `org_id` to `agents`, `runs`, and `test_results`.
- Add an index on `(org_id, started_at)`.
- Add `org_id: str` as a required leading parameter to every public method: `save_run`, `list_agents`, `list_tests`, `list_runs`, `run_count`, `get_run`, and `pass_fail_matrix`.
- Do not default `org_id`. A forgotten argument must be a `TypeError` at test time, never a silent cross-tenant read.
- `get_run(org_id, run_id)` raises `KeyError` for another org's run, the same response as not found. Do not leak existence.

**Acceptance:** A two-org fixture proves every read method returns only the calling org's rows; `get_run` on a foreign run raises `KeyError`; no method has a default `org_id`.

**Validate:**

```powershell
python -m pytest tests/test_store.py
python -m pytest
```

### T3: Extract `load_target_dict` - Done

**Dependencies:** none
**Files:** `backend/agentkit/core/config.py`, `tests/test_config.py`

Targets must be loadable from a DB row, not only a file path.

- Add `load_target_dict(raw: dict) -> TargetConfig` containing the validation currently inlined in `load_target`: env interpolation (`config.py:54`), sandbox check (`config.py:95`), and HTTP endpoint check (`config.py:103`).
- Make `load_target(path)` a thin file-reading wrapper over `load_target_dict`.
- Keep CLI behavior unchanged.
- Keep `${ENV_VAR}` interpolation server-side; secrets never sit in stored config.

**Acceptance:** `load_target(path)` and `load_target_dict(yaml.safe_load(text))` produce identical `TargetConfig` objects for every fixture in `agentkit/config/`.

**Validate:**

```powershell
python -m pytest tests/test_config.py tests/test_cli.py
```

### T4: Add `load_tests_from_rows` - Done

**Dependencies:** none
**Files:** `backend/agentkit/core/loader.py`, `tests/test_loader.py`

- Add `load_tests_from_rows(rows: list[dict]) -> list[TestCase]`.
- Reuse the existing `_build_test_case` (`loader.py:59`) verbatim. It already enforces the assertion registry (`loader.py:80`), category/risk enums, and input-xor-turns rule.
- Do not write new validation.
- Leave `discover()` and `load_python_module()` untouched. They remain the first-party path used by the CLI and by packs shipped in the image.

**Acceptance:** A row-sourced `TestCase` equals the file-sourced one for identical content; an unknown assertion name in a row raises `LoaderError` exactly as from a file.

**Validate:**

```powershell
python -m pytest tests/test_loader.py
```

### T5: Targets and Packs as DB Rows - Done

**Dependencies:** T2, T3, T4
**Files:** `backend/agentkit/core/store.py`, new migration, `tests/test_store.py`

- Add `targets (id, org_id, name, config_json, created_at, secret_ref)`.
- Add `packs (id, org_id, name, created_at)`.
- Add `pack_tests (id, org_id, pack_id, test_id, test_json)`, one serialized `TestCase` per
  row, unique by `(org_id, pack_id, test_id)`.
- Add target, pack, and pack-test CRUD, all `org_id`-scoped per T2's convention.
- Secrets are not in `config_json`. Sensitive values remain `${ENV_VAR}` references and require
  a separate opaque `scheme://` `secret_ref`; resolution remains T15. Literal credentials are
  rejected before persistence.
- Target row IDs must equal the stored config ID. DB-backed packs reject duplicate test IDs just
  like filesystem discovery.

**Acceptance:** A target round-trips through `config_json -> load_target_dict -> equal
TargetConfig`; a pack round-trips via `load_tests_from_rows`; cross-org reads and mutations see
nothing; literal secrets, mismatched target IDs, malformed tests, and duplicate test IDs are
rejected without partial writes.

**Validate:**

```powershell
python -m pytest tests/test_store.py
python -m pytest
```

## Phase 2: Identity via Keycloak

Ships before any external partner gets interactive access. A shared credential has no attribution on who launched a run, and revoking one person logs out the whole org. For a tool whose output is evidence, unattributable actions defeat the product.

### T6: Keycloak Infrastructure and Realm - Done

**Dependencies:** none
**Files:** `infra/docker-compose.yml`, `infra/keycloak/agentkit-realm.json`, `docs/`

- Add a Keycloak service with its own database, separate from AgentKit's.
- Use one realm and one group per org.
- Add a protocol mapper that puts the org into an `org_id` token claim.
- Do not add a local memberships table. Keycloak is the single source of truth for identity and org membership.
- Humans use OIDC Authorization Code + PKCE. Keycloak owns sessions, reset, MFA, and revocation.
- CI/service access uses Keycloak service accounts with the client-credentials grant, one client per partner.
- Version-control the realm config as exported realm JSON in `infra/keycloak/`.
- Keycloak is authoritative for identity and org membership only, not application authorization logic. Keep roles coarse (`admin`/`viewer`) or policy gets debugged in two places.

**Acceptance:** `docker compose up` yields a realm importable from checked-in JSON; a test user in an org group receives a token carrying the `org_id` claim.

**Validate:** Static deployment-contract tests plus a manual browser login and decoded access-token
check. Service accounts use client credentials; human passwords are never sent to the token endpoint.

### T7: JWT Validation Dependency - Done

**Human review required.**

**Dependencies:** T6, T2
**Files:** `frontend/agentkit/web/app.py`, `tests/test_web.py`

- Replace process-global `_ACCESS_TOKEN` / `_require_token` with a typed `Principal` carrying org,
  subject, email, realm roles, and authentication method.
- Validate JWTs against Keycloak's JWKS. Cache keys and refresh on unknown `kid`.
- Read `org_id` from the validated claim only, never from a request parameter, path segment, or form field.
- Verify signature, `exp`, `iss`, and `aud`. A token failing any check is `401`.
- Do not stand up Keycloak in the test suite. Sign test tokens with a static test keypair.

**Acceptance:** Valid token returns a principal; expired, wrong-issuer, wrong-audience, and bad-signature tokens each return `401`; an `org_id` supplied as a query parameter is ignored.

**Validate:**

```powershell
python -m pytest tests/test_web.py
```

**Review:** Signature/claim validation that is subtly wrong can pass tests and still be exploitable. A human reads this diff.

### T8: Scope Every Route - Done

**Dependencies:** T7, T5
**Files:** `frontend/agentkit/web/app.py`, `tests/test_web.py`

- Apply `current_principal` to every application route, not just state-changing ones. The login,
  callback, and logout protocol endpoints are deliberately public.
- Require the coarse `admin` role for mutations; `viewer` is read-only. Browser-session mutations
  also require a CSRF token.
- Pass `org_id` into every Store call. Because T2 made it required, a missed route fails loudly rather than serving another partner's data.
- Record `created_by` using the Keycloak `sub`, plus denormalized email for display, on runs and authored tests.

**Acceptance:** Every protected route rejects an unauthenticated API caller; browser requests enter
Authorization Code + PKCE; viewers cannot mutate; org B fetching org A's run id gets `404`, not
`403`; runs display who launched them.

**Validate:**

```powershell
python -m pytest tests/test_web.py
python -m pytest
```

### T9: Delete the Filesystem Test Write - Done

**Dependencies:** T5, T8
**Files:** `frontend/agentkit/web/app.py`, `tests/test_web.py`

This closes the crosstalk hole. `app.py:421` currently writes tenant-authored tests to `get_packs_dir()/user/<id>.yaml`, a directory every org's `discover()` walks.

- Replace the file write with an insert into `pack_tests` scoped to the caller's org.
- Keep the existing validation path: `TestCase.model_validate` and the `ASSERTION_REGISTRY` check at `app.py:418`.
- Make `/tests` read from `pack_tests` for the caller's org.

**Acceptance:** A test authored by org A is invisible to org B in the UI and in the DB; no code path writes to `packs/user/` anymore.

**Validate:**

```powershell
python -m pytest tests/test_web.py
```

### T10: Connection Pool - Done

**Dependencies:** T2
**Files:** `frontend/agentkit/web/app.py`, `tests/test_web.py`

Use one long-lived `Store` and a bounded SQLite connection pool. Each operation exclusively leases
a connection for its complete transaction, then returns it. App shutdown closes idle connections
immediately and leased connections when they return.

**Acceptance:** Connection count stays within the configured bound across requests and concurrent
threads; `close()` rejects new checkouts and leaks no idle handles.

**Validate:**

```powershell
python -m pytest tests/test_web.py
```

## Phase 3: Asynchronous, Concurrent Runs

### T11: Jobs Table with Lease Fields

**Dependencies:** T2
**Files:** new migration, `backend/agentkit/core/store.py`, `tests/test_store.py`

Add `jobs`:

```text
id, org_id, target_id, pack_id, state, run_id, created_by, error, priority,
attempt_count, created_at, started_at, finished_at, lease_owner,
lease_expires_at, heartbeat_at
```

`state` is one of `queued`, `running`, `done`, or `failed`.

**Acceptance:** `claim`, `heartbeat`, `release`, and `reclaim` helpers exist on `Store` and are org-scoped for reads.

**Validate:**

```powershell
python -m pytest tests/test_store.py
```

### T12: Worker Process

**Dependencies:** T11
**Files:** `backend/agentkit/worker.py`, `pyproject.toml`, `tests/test_worker.py`

- Add a worker loop: select queued jobs ordered by priority and creation time with `FOR UPDATE SKIP LOCKED LIMIT 1`, claim with `lease_owner` and `lease_expires_at`, run, and persist.
- Call unchanged `core.runner.run`, then score, then `store.save_run`.
- Use a real lease with heartbeat, not stale-`started_at` reclaim. The worker extends `lease_expires_at` on an interval well under the lease duration. A job is reclaimable only once the lease expires.
- Reclaim increments `attempt_count`; fail past a ceiling.
- Retry infrastructure failures only. Never auto-retry an agent failure; `runner.py` turns those into `Status.ERROR` results, which are evidence, not errors.
- Cap concurrent running jobs per org before dequeue so one partner cannot starve others.

`SKIP LOCKED` means N workers need no coordination and no broker.

**Acceptance:** Two workers never double-claim; an expired lease is reclaimed; a heartbeating long job is not reclaimed; per-org cap holds.

**Validate:**

```powershell
python -m pytest tests/test_worker.py
```

### T13: Async Submission and Real Status

**Dependencies:** T12
**Files:** `frontend/agentkit/web/app.py`, templates, `tests/test_web.py`

- `POST /runs` (`app.py:655`) inserts a job and returns immediately; it no longer calls `run_tests`.
- `run_status` (`app.py:624`) currently has dead branches because a persisted run always has `finished_at`, so `running` is never true. Repoint it at jobs for real state.
- Reuse the existing `_status_fragment.html` and `static/poll.js` polling pattern that `frontend/agentkit/web/CLAUDE.md` prescribes. Do not invent a second mechanism.

**Acceptance:** `POST /runs` returns without executing; the job is queued and no run row exists yet; the status endpoint reports genuine queued/running/done states.

**Validate:**

```powershell
python -m pytest tests/test_web.py
```

### T14: Artifact Storage Policy

**Dependencies:** T2, T8
**Files:** new migration, `backend/agentkit/core/artifacts.py`, `frontend/agentkit/web/app.py`

Decide this now even though object storage is deferred. Evidence blobs are where cross-tenant leakage reappears, because the first thing that writes a file inherits none of T2's scoping.

- Keep structured evidence in Postgres, in `test_results.result_json` as today. It is already org-scoped and already redacted twice.
- Put any blob, including future traces, screenshots, or generated reports, under a mandatory `{org_id}/{run_id}/{artifact_id}` prefix.
- Store blob metadata in `artifacts (id, org_id, run_id, kind, size, path, created_at)`.
- No component constructs an artifact path itself. One helper in `core/` owns path construction and takes `org_id` as a required argument.
- Serve artifacts only through an authenticated route checking the row's `org_id` against the token claim. Never serve them as static files.
- Because the prefix is fixed from day one, swapping in object storage later is a backend change, not a migration.

**Acceptance:** The path helper cannot produce a path without an `org_id`; an artifact of org A is `404` with an org B token; no static mount exposes the artifacts root.

**Validate:**

```powershell
python -m pytest tests/test_artifacts.py tests/test_web.py
```

### T15: Secret Resolution and Egress Allowlist

**Human review required.**

**Dependencies:** T12
**Files:** `backend/agentkit/worker.py`, `backend/agentkit/core/agent.py`, `tests/test_security_p0.py`

#### Secrets

- Resolve `secret_ref` in the worker at run start, for that run only.
- Pass the resolved value to the subprocess environment.
- Never write the resolved value to `config_json`, logs, the jobs table, or evidence.
- Keep the existing `Redactor` as the last line of defense, not the first.
- Prefer short-lived credentials. Where the partner's system cannot issue them, scope the long-lived secret to the single target.

#### Egress

This closes an SSRF hole, not a hardening nice-to-have.

- `HTTPSpec.endpoint` (`config.py:34`) is partner-supplied and handed to `httpx`, so an unrestricted worker is an SSRF primitive.
- Store a host allowlist on the target.
- Validate the resolved endpoint at run start.
- Block link-local, loopback, and private ranges by default after DNS resolution, so a hostname resolving to `169.254.169.254` is rejected. Validating the string alone is insufficient.
- Run workers in a network segment with no reach to the control-plane database or cloud metadata endpoint.

**Acceptance:** A target pointing at `169.254.169.254` is rejected before any request; a hostname resolving to a private address is also rejected; a resolved secret appears in no log, table, or evidence payload.

**Validate:**

```powershell
python -m pytest tests/test_security_p0.py tests/test_redaction.py
```

**Review:** DNS-rebinding and allowlist bypasses pass naive tests. A human reads this diff.

## Phase 4: Killable Run Isolation

### T16: Subprocess Execution - Done

**Human review required.**

**Shipped:** `backend/agentkit/core/isolation.py`. One spawned supervisor per `run()` owns
the real sandbox and evaluates tests. Agent code runs in a nested spawned worker against an
RPC sandbox proxy. On timeout the worker process tree is killed before the supervisor takes
the after-snapshot, so no live agent can race or alter the recorded diff. The worker is
restarted for the next test while the supervisor and sandbox remain scoped to the run.

Both YAML and `PythonTestCase` tests use this path; Python functions cross the boundary with
`cloudpickle`. The parent keeps the `turns * timeout_s + grace` hard deadline and converts
startup, serialization, child-death, and deadline failures into `Status.ERROR`. POSIX uses
process groups plus hard CPU/address-space rlimits. Windows uses nested kill-on-close Job
Objects with per-process CPU and memory limits, so descendants are reaped on timeout too.

**Dependencies:** none. This is ungated and worth shipping single-tenant.
**Files:** `backend/agentkit/core/isolation.py`, `backend/agentkit/core/runner.py`,
`backend/agentkit/core/schema.py`, `tests/test_isolation.py`, `tests/test_runner.py`

`runner.py:30` documents the defect: `_run_with_timeout` submits to a `ThreadPoolExecutor` and abandons the thread on timeout, because CPython has no thread-kill primitive. A hung agent leaks a thread and socket per timeout. `runner.py:118` must discard the sandbox diff since the orphan may still be mutating it, so a timed-out test yields no usable evidence.

- Execute each run in a subprocess.
- Enforce the timeout by killing the process tree.
- Use `ProcessPoolExecutor` or plain subprocess with a `RunResult` over a pipe. No container runtime at this scale.
- With a killable worker, the timeout path can trust sandbox state again. Replace the `diff = None` branch at `runner.py:126` with a real diff, and delete the comment at `runner.py:33` along with the leak it describes.
- Set CPU, memory, and wall-time ceilings on the child.
- `runner.py` must still never raise; subprocess crashes become `Status.ERROR`.

**Acceptance:** An agent sleeping past its timeout is reaped with no orphan process; the result carries a trustworthy diff; no exception escapes `run()`.

**Validate:**

```powershell
python -m pytest tests/test_runner.py
python -m pytest
```

**Review:** This changes what counts as trustworthy evidence. A human reads this diff.

## Phase 5: Deployment

### T17: Compose, Network Policy, Cutover

**Dependencies:** T13, T15
**Files:** `infra/docker-compose.yml`, `infra/Dockerfile`, `docs/`

- Add Postgres and Keycloak, with Keycloak using its own DB, in compose.
- Run migrations by explicit deploy step, never implicitly on app startup.
- Run web and worker as separate services from the same image, differing only in command.
- Put web and worker on different network policies: only web reaches Keycloak's public endpoints; only the worker reaches partner endpoints; the worker does not reach the control-plane DB directly if avoidable.
- `AGENTKIT_DB` becomes a Postgres DSN.
- Keep SQLite for local dev and the test suite while it stays free; drop it the moment it costs branches in `store.py`.
- Bind `0.0.0.0` only behind TLS and T7's dependency.

The `127.0.0.1` default in `.claude/rules/security-sensitive.md` exists because the run endpoint executes packs. That reasoning retires only once tenant packs are YAML-only (T5/T9) and every route is authenticated (T8), not before.

## End-to-End Verification

Run this after the phases land.

1. Run the full suite and validation script:

   ```powershell
   python -m pytest
   bash tools/validate.sh
   ```

2. **Two-org isolation:** two Keycloak users in different org groups; author a test as A and run it; confirm B's `/tests`, `/runs`, and `/agents` are empty; B fetching A's run id returns `404`; the run records A's user as `created_by`.

3. **Revocation:** disable user A in Keycloak; their session stops working; the org's other users are unaffected.

4. **Concurrency:** enqueue several runs and start two workers; both progress, no job is double-claimed, and killing one worker mid-run lets the other reclaim only after lease expiry.

5. **Isolation:** point a target at a hanging agent; the run times out, the child is reaped, and a usable sandbox diff is still recorded.

6. **Egress:** targets at `169.254.169.254` and at a hostname resolving to a private address are both rejected before any request.

7. **Regression canary:** this still works unchanged:

   ```powershell
   agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml
   ```

   The CLI's file-based path proves T3/T4/T5 did not break first-party packs.

## Amendment: T1 Uses Alembic, Not Hand-Rolled Raw SQL

**Date:** 2026-07-18

Original T1 decided against Alembic/ORM: "No ORM, but strict migration discipline" and "Create ordered raw-SQL migrations with real versioning. No Alembic, no ORM." The user explicitly overrode this during implementation and asked for Alembic instead.

### What Actually Shipped for T1

- Alembic and SQLAlchemy were added as dependencies in `pyproject.toml`, used only as migration tooling.
- `alembic` and `sqlalchemy` are required transitively for the migration runner; they are not imported anywhere else in the codebase.
- `store.py` is untouched and still the only runtime DB access point, still plain `sqlite3`.
- Alembic drives schema evolution; it does not become a second way to read/write app data.
- Layout:
  - `alembic.ini` at repo root with `script_location = infra/alembic`
  - `infra/alembic/env.py` as a raw-SQL env with `target_metadata = None` and no ORM models
  - `infra/alembic/versions/0001_baseline_schema.py` containing the same `agents`/`runs`/`test_results` schema `Store` already creates
- The migration package is included in built wheels.
- The application resolves the script directory through package resources rather than assuming a source checkout.
- The baseline uses `op.execute("CREATE TABLE IF NOT EXISTS ...")`, so it is idempotent against a DB `Store` already initialized directly.
- `agentkit migrate [--db PATH] [--status]` is a CLI subcommand in `backend/agentkit/cli.py` wrapping `alembic.command.upgrade`, with `sqlalchemy.url` set dynamically from `--db` per invocation.
- Status lists pending revisions in application order, or reports that the database is up to date.
- The old `infra/migrations/*.sql` custom raw-SQL engine and `backend/agentkit/migrate.py` hand-rolled runner were deleted.
- `tests/test_migrate.py` verifies clean application to a fresh DB, idempotent second invocation, resume from a partially-created baseline, pending/up-to-date status output, and the `alembic_version` table.

Future tasks that touch migrations, including T2, T5, T11, and T14, should add an Alembic revision under `infra/alembic/versions/` via:

```powershell
alembic revision -m "<name>"
```

Alternatively, create the revision by hand following `0001_baseline_schema.py`'s pattern. Do not add a new `infra/migrations/NNNN_name.sql` file; that directory no longer exists.

### T5 Integrity Follow-up

T5 originally landed as revision `0003`. The review fixes ship in follow-up revision `0004`
rather than rewriting an applied revision. It adds `targets.secret_ref`, gives `pack_tests` an
explicit tenant-scoped test identity and uniqueness constraint, and validates foreign-key lineage
after rebuilding tables. Direct `Store` initialization and the full Alembic chain are required to
produce equivalent schemas.
