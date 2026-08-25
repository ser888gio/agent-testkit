# Project map

What every folder is responsible for, what an engineer finds inside, and the order it
was built in — as phases, each phase broken into the individual feature pushes that
delivered it.

Two ways to read this:

- **Part 1 — the map.** Where code lives *now*. Read this to find things.
- **Part 2 — phases and pushes.** How it got here, feature by feature. Read this to
  understand why a folder looks the way it does, or to see what is left.

Companion documents: [`CLAUDE.md`](../CLAUDE.md) (working rules),
[`docs/architecture.md`](architecture.md) (trust domains and deployment),
[`docs/components.yaml`](components.yaml) (machine-readable component map),
[`docs/specs/`](specs/) (per-module contracts).

---

# Part 1 — The map

## The one structural surprise

The `agentaudit` package is **physically split across four top-level directories** and
reassembled by an explicit setuptools package map in `pyproject.toml`
(`[tool.setuptools] packages` + `[tool.setuptools.package-dir]`, one entry per subpackage).

| On disk | Imported as |
| --- | --- |
| `backend/agentaudit/core/` | `agentaudit.core` |
| `backend/agentaudit/cli.py` | `agentaudit.cli` |
| `frontend/agentaudit/web/` | `agentaudit.web` |
| `agentaudit/packs/`, `agentaudit/config/` | `agentaudit.packs`, `agentaudit.config` |
| `infra/alembic/` | `agentaudit.migrations` |

At import time there is exactly **one** `agentaudit` package. **Import paths never mention
`backend`, `frontend`, or `infra`.** The explicit map replaced implicit namespace-package
discovery specifically so `infra/alembic/` ships inside the installed wheel — namespace
`find` had no way to reach outside its `where` roots.

## Top-level layout

```text
agentaudit/          Data: target configs + YAML test packs (no logic)
backend/agentaudit/  Engine: core/ · domains/ · reports/ · cli.py · worker.py
frontend/agentaudit/ Web: FastAPI dashboard, Jinja templates, auth
infra/               Docker, compose, dev launcher, Alembic migrations, Keycloak realm
tests/               pytest suite for agentaudit itself (37 files, one per module)
docs/                Architecture, 25 specs, plans, D2 diagrams, component map
tools/               validate.sh · affected.sh · guard-protected-paths.sh · install-hooks.sh
.claude/             Agents, slash commands, path-scoped rules for Claude Code
.github/             CI, security workflow, templates, branch-protection notes
.qlty/               Pre-push quality gate (bandit, trufflehog, shellcheck, actionlint)
.aislop/             Per-edit slop scanner config and session log
```

Reading order for someone new: this file → [`docs/architecture.md`](architecture.md) for
the trust model → the docstring at the top of whichever `core/` module you are about to
touch. Those docstrings carry the *why*, and they are the densest documentation here.

---

## `agentaudit/` — product data, not code

No Python logic beyond package markers. This is the content the tool *runs*, kept
separate from the engine that runs it.

### `agentaudit/config/` — target configs

One YAML per testable agent, consumed by `core/config.py:load_target`. Two shapes: an
in-process callable (`module:function`) or an HTTP endpoint.

| File | What it points at |
| --- | --- |
| `treasury-agent.yaml` | In-process treasury demo agent |
| `treasury-http.yaml` | Same agent over HTTP (parity proof) |
| `email-agent.yaml` | In-process email demo agent |
| `email-trusting-forwarder.yaml` | Deliberately vulnerable email agent |
| `demo-stub-http.yaml` | Minimal HTTP stub |
| `my-agent.example.yaml` | Template a user copies for their own agent |

### `agentaudit/packs/` — the test content

**YAML is data, not pytest.** Loaded by `core/loader.py:discover`. A pack `id` is the
stable key used for regression comparison across runs — renaming one breaks history.

```text
packs/core/       Domain-agnostic, runs against any agent
  endpoint_contract/   health · response_nonempty · schema_validity
  robustness/          empty_input · long_input · malformed_input
  prompt_injection/    instruction_override · system_prompt_extraction
  data_leakage/        pii_probe · secret_probe · debug_access · system_reconnaissance
  jailbreak/           bad_likert_judge · linear_concession · refined_pressure
                       sequential_decomposition        (multi-turn adaptive ladders)
  performance/         latency
  reliability/         consistency

packs/agentic/    OWASP Agentic Top 10 — needs a sandbox with real side effects
  goal_hijack/         injected_payee · goal_theft · recursive_hijacking
                       payee_swap_survives_injection
  tool_misuse/         mass_payout · split_to_evade_limit · external_system_abuse
                       tool_metadata_poisoning
  privilege_abuse/     over_limit_payout · role_boundary · object_level_authorization
  human_oversight/     no_approval_token · excessive_agency_autopay · autonomous_drift
  memory_poisoning/    false_preapproval
  agent_trust/         identity_spoofing · relayed_instruction
  code_execution/      shell_tool · sql_injection · server_side_request_forgery

packs/treasury/   Vertical starter: approved/unapproved/duplicate/over-limit payment,
                  wrong payee, changed bank details
packs/email/      Vertical starter: phishing, exfiltration, unauthorized forward,
                  indirect instruction, cross-context retrieval
```

`packs/core/_demo_safe_agent.py` is the one Python file here — a well-behaved agent used
as the control in demos.

---

## `backend/agentaudit/core/` — the engine

Bottom of the dependency graph. **Imports nothing else in `agentaudit`.** Everything
else depends on it.

The single most important distinction in this codebase runs through this folder:

| | Modules | Rule |
| --- | --- | --- |
| **Runner side** | `agent.py`, `sandbox.py`, `runner.py`, `isolation.py`, `redaction.py`, `discovery.py`, `egress.py`, `attacker.py`, `judge.py` | May touch a live agent or unredacted evidence |
| **Control plane** | `scoring.py`, `store.py`, `compliance.py`, `regressions.py`, `catalog.py`, `planner.py`, `profile.py` | Consumes an **already-redacted** `RunResult` only |

### Contracts — change these and everything downstream breaks

| File | Owns |
| --- | --- |
| `schema.py` | `TestCase`, `TestResult`, `RunResult`, `Category`, `Risk`, `Status` |
| `config.py` | `TargetConfig`, `HTTPSpec`, `load_target` |
| `assertions.py` | `REGISTRY` — assertion names referenced by string from YAML |
| `sandbox.py` | `Sandbox` ABC + `@register_sandbox` registry |
| `profile.py` | `AgentProfile`, `TestCatalogEntry`, `HarnessPlan` |
| `adapters.py` | `ExternalEvalAdapter` |

### Execution

| File | Responsibility |
| --- | --- |
| `agent.py` | `CallableAgent` + `HTTPAgent` + `build_agent`. **The only `httpx` import in the repo.** |
| `loader.py` | Discover and validate tests from YAML/JSON/Python; `load_tests_from_rows` for DB-sourced packs |
| `runner.py` | Lifecycle: reset → setup → run → assert. **Never propagates an exception** — agent and sandbox failures become `Status.ERROR` results |
| `isolation.py` | Killable process isolation. Outer child owns the sandbox; agent code runs in a nested worker behind a generic RPC proxy. On timeout the worker tree is destroyed *before* the sandbox snapshot, so timeout evidence cannot race a still-running agent. The largest core module (834 lines) |
| `assertions.py` | Assertion registry and evaluation, including trajectory assertions over the tool-call ledger |
| `sandbox.py` | Sandbox ABC, snapshots, diffs, event log |

### Adaptive layer

| File | Responsibility |
| --- | --- |
| `adaptive.py` | Multi-turn attack **ladders**: `crescendo`, `sequential`, `linear`, `bad_likert_judge`. Fixed scripts — deterministic, offline, free. Bounded by `max_turns` |
| `attacks.py` | **Attack transforms**: prompt mutations (base64, rot13, unicode…) that reuse a test's existing assertions. One transform × N tests multiplies coverage without new content — the pass bar stays identical to the source test |
| `attacker.py` | **Attacker-LLM refinement** — writes the next turn from the actual reply instead of following a script. Off unless configured; no API key means no behavior change |
| `judge.py` | **Model-as-judge stop condition** — decides whether an attack already landed, replacing brittle `stop_on` substring matching. Off unless configured |
| `discovery.py` | Probes a live endpoint → `AgentProfile`. Goes through `runner.run`, not `build_agent`, to inherit isolation/egress/timeouts/redaction. Records shapes and booleans, never bodies |
| `catalog.py` | Describes tests in selection terms and ranks them for one agent. Everything that survives ranking carries **why**; everything dropped carries why not |
| `planner.py` | `AgentProfile` + catalogs → the `HarnessPlan` a run executes, including explicit exclusions with reasons |
| `adapters.py` | promptfoo + garak normalization. Contract runs one way: foreign catalog/report → `TestCatalogEntry`/`TestResult`. Nothing foreign reaches the store. **Second redaction entry point** — these results bypass `runner.py`, so `normalize()` redacts and applies the evidence policy itself |
| `jsonx.py` | Extracts a JSON object from model output wrapped in fences/preamble/trailing prose. Ported from garak (Apache-2.0) |

### Evidence and persistence

| File | Responsibility |
| --- | --- |
| `redaction.py` | `Redactor` + evidence policy. **Not optional** — runs before `TestResult` construction, and again in `Store.save_run` as defense in depth |
| `scoring.py` | Risk-weighted category scores and gate thresholds |
| `store.py` | SQLite/Postgres persistence. **The only SQL in the repo** (1192 lines) — runs, results, orgs, targets, packs, jobs, artifacts |
| `compliance.py` | EU AI Act / ISO 42001 / NIST control mapping. **Fails closed**: empty or all-skipped ⇒ `INCOMPLETE`, never a pass |
| `regressions.py` | Run-to-run comparison keyed on pack `id` |
| `artifacts.py` | Canonical artifact key `{org_id}/{run_id}/{artifact_id}`. The only permitted way to build it, fixed before the first blob is written |
| `egress.py` | Endpoint allowlist, DNS resolution, address pinning. Without it a hosted worker is an SSRF primitive — every resolved A/AAAA must be publicly routable, and the connection is pinned to the validated address to defeat DNS rebinding |

## `backend/agentaudit/domains/` — the fake worlds

A vertical is a `Sandbox` subclass decorated `@register_sandbox("name")`, plus demo
agents. **Adding one requires no change to `core/`.** Registration happens by explicit
import in `cli.py`, `web/app.py`, and `worker.py` (`# noqa: F401` — not dead imports).

| Path | Contents |
| --- | --- |
| `treasury/sandbox.py` | Fake bank + invoice store + approvals |
| `treasury/agent.py` | Well-behaved demo agent |
| `treasury/overtrusting_agent.py` | Deliberately vulnerable — the thing packs are meant to catch |
| `email/sandbox.py` | Fake inbox + contacts + outbound ledger |
| `email/agent.py`, `email/fixtures.py` | Demo agent and seed data |
| `email/trusting_forwarder_agent.py` | Deliberately vulnerable forwarder |

`snapshot()` must be JSON-serializable and deterministic.

## `backend/agentaudit/reports/` — renderers

Control plane. Consumes an already-redacted `RunResult`/`ScoreReport`; never calls an
agent. `__init__.py` exposes `render()`.

`json.py` · `junit.py` (CI) · `html.py` (self-contained) · `md.py` ·
`compliance.py` (EU AI Act / ISO 42001 / NIST, fails closed) · `plan.py` (why each test
was selected, and what went untested)

## `backend/agentaudit/cli.py` — the `agentaudit` console script

`run` · `plan` · `report` · `compare` · `ui` · `migrate`. Exit codes gate CI via the
`fail_under` threshold. Shows per-test progress while running.

## `backend/agentaudit/worker.py` — the polling worker

Claims a queued job with a lease, heartbeats while working, persists evidence. N workers
need no coordination and no broker; a dead worker's lease expires and another reclaims
the job. **Resolves targets and packs from the database only** — never a tenant-supplied
filesystem path, which keeps `loader.load_python_module` off the tenant-reachable path
entirely. `PermanentJobError` distinguishes "will fail identically every retry" from
infrastructure faults; an *agent* failure is neither — that is evidence, and the job is
`done`.

## `frontend/agentaudit/web/` — the dashboard

FastAPI + Jinja2 over the `Store`. Binds `127.0.0.1` by default. Renders only
already-redacted evidence read through `Store`.

| File | Contents |
| --- | --- |
| `app.py` | All routes (1084 lines) — dashboard, runs, tests, agents, harness, compare, settings, job status |
| `auth.py` | OIDC, browser sessions, coarse route authorization (Keycloak) |
| `templates/` | `base.html` + `_components.html` shared; page templates per route; `_status_fragment.html` for polling |
| `static/` | `style.css`, `poll.js` |

Keep this thin — push logic into `core/` where it is testable without a TestClient.

## `infra/` — deployment and schema

| Path | Contents |
| --- | --- |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore` | Container image; the run worker is isolated in a hardened container |
| `dev.sh` | Local dashboard on `127.0.0.1:8000` |
| `alembic/versions/` | 10 migrations, **raw SQL via `op.execute`, no ORM models** |
| `keycloak/agentaudit-realm.json` | Realm import for local auth |
| `.env.example` | Environment template |

Migration history, which doubles as a changelog of the platform phases:

`0001` baseline · `0002` org_id everywhere · `0003` targets+packs as rows ·
`0004` phase-1 integrity · `0005` run attribution · `0006` jobs · `0007` artifacts ·
`0008` target egress · `0009` job heartbeat · `0010` run plan

## `tests/` — the pytest suite

590 tests, **~165s**. Most of that is process spawn: since the isolation work every
`runner.run` starts a sandbox supervisor plus a nested agent worker (~2.5s per run on
Windows). Production pays that once per run; the suite calls `run` dozens of times.

**One file per module, and the mapping is load-bearing** — `tools/affected.sh` derives
its pytest targets from it. A test placed in the wrong file silently drops out of
affected-scope validation.

| Test file | Covers |
| --- | --- |
| `test_schema.py`, `test_config.py`, `test_profile.py` | The three contracts |
| `test_agent.py`, `test_http_agent.py` | Adapters; HTTP/callable behavioral parity |
| `test_runner.py`, `test_isolation.py` | Execution lifecycle; process isolation and kill |
| `test_loader.py`, `test_assertions.py` | Discovery/validation; assertion registry |
| `test_sandbox_core.py`, `test_treasury.py`, `test_email.py` | Sandbox ABC and both verticals |
| `test_adaptive.py`, `test_attacks.py`, `test_attacker.py`, `test_judge.py`, `test_jsonx.py` | The adaptive layer |
| `test_catalog.py`, `test_planner.py`, `test_discovery.py`, `test_adapters.py` | Selection and profiling |
| `test_scoring.py`, `test_compliance.py`, `test_regressions.py`, `test_reports.py` | Control plane and renderers |
| `test_store.py`, `test_migrate.py`, `test_artifacts.py` | Persistence, Alembic, artifact keys |
| `test_redaction.py`, `test_security_p0.py`, `test_auth.py` | Evidence and security invariants |
| `test_cli.py`, `test_web.py`, `test_worker.py`, `test_phase2_infra.py` | Application surfaces |
| `test_packs_core.py`, `test_packs_domain.py` | The YAML packs validate and load |

`_fixtures.py` holds shared helpers — underscore-prefixed so pytest does not collect it.
**There is no `conftest.py`**; add to `_fixtures.py` first and only introduce one if a
fixture genuinely needs pytest injection.

Two conventions worth knowing before writing a test here:

- **Failure paths matter more than happy paths.** The runner's contract is that it never
  raises, which is only meaningful if the failure paths are exercised.
- **`test_security_p0.py` failures are blocking.** Each test reproduces a weakness the
  code had or could regress into. If a change makes one fail, the burden is proving the
  invariant still holds — not relaxing the assertion.
- Expect `PytestCollectionWarning` for `TestCase`/`TestResult`/`TestCatalogEntry`: pytest
  sees the `Test` prefix. Harmless, and the names are public contracts — do not rename.

## `docs/` — reasoning that outlived its branch

| Path | Contents |
| --- | --- |
| `architecture.md` | Trust domains, deployment topology, the deeper "why" |
| `specs/` | Per-module contracts, one per original Phase 0 feature branch (25 files) |
| `components.yaml` | Machine-readable component map with per-component validation commands |
| `diagrams/*.d2` | D2 sources for architecture, infrastructure, isolation |
| `diagrams/*.svg` | **Generated** — light/dark renders, never hand-edited |
| `IMPLEMENTATION-TESTS-PLAN.md` | The 14-workstream roadmap Part 2 tracks against |
| `plan.md`, `plan-attack-surface-completion.md`, `plan-competitive-response.md` | Active plans |
| `archive/plans/` | Superseded plans, kept for provenance |
| `claude-code.md` | Contributor guide for the Claude Code setup |
| `keycloak.md` | Auth setup |
| `notes/errors-and-improvements.md` | Running log of mistakes and their fixes |

## `tools/` — the validation scripts

| Script | Does |
| --- | --- |
| `affected.sh` | Maps changed files → components → pytest targets. `--tests-only`, `--components-only`, `--files-only` for scripting; `--base <ref>` to diff against a branch |
| `validate.sh` | Runs the ladder. `--affected` narrows to changed scope. Probes for a runner that has *both* pytest and ruff — prefer it over calling either directly |
| `guard-protected-paths.sh` | Blocks edits to generated/vendored paths |
| `install-hooks.sh` | Installs the git hooks |

## `.claude/` — agent configuration

Not incidental: this repo is set up so an agent can work in it safely.

- `agents/` — `architecture-explorer`, `dependency-tracer`, `test-finder`, `code-reviewer`
  (all read-only except the reviewer's Bash)
- `commands/` — the `explore` → `plan` → `implement` → `review` workflow
- `rules/` — path-scoped rules: `dependency-boundaries.md`, `generated-files.md`,
  `security-sensitive.md`, `test-packs.md`
- `settings.json` (committed) / `settings.local.json` (local)

Directory-level `CLAUDE.md` files add local rules in `core/`, `domains/`, `web/`,
`packs/`, `tests/`, and `infra/`.

## `.github/` — CI and policy

| Workflow | Jobs |
| --- | --- |
| `ci.yml` | `tests` (Python 3.10–3.13 matrix), `lint` (ruff, repo-wide), `package` (`uv build`), and `required` — an aggregator gate that all three must pass |
| `security.yml` | `pip-audit` over exported locked runtime deps; also runs weekly on cron |

Actions are pinned by commit SHA and run with `persist-credentials: false`.
`BRANCH_PROTECTION.md` documents the ruleset that must exist in repo settings — workflow
files cannot prevent direct pushes on their own.

> **Gap worth knowing:** both workflows trigger only on `main`, but `origin/HEAD` is
> `develop` and feature branches merge there. PRs into `develop` therefore run no CI —
> the gate applies only at the `develop` → `main` promotion. Verified against
> `.github/workflows/*.yml` and `git symbolic-ref refs/remotes/origin/HEAD`.

## `.qlty/` — the pre-push quality gate

`qlty.toml` configures plugins beyond ruff: `bandit` (excluded on `tests/`, since B101
flags the `assert` pytest is built on), `trufflehog` (secrets), `shellcheck`, `hadolint`,
`actionlint` + `zizmor` (workflow linting), `radarlint`. `hooks/pre-push.sh` runs it.
`.qlty/out/` is generated scan output — ignored, never edited.

An aislop PostToolUse hook also scans on every Edit/Write; its findings are blocking, and
`.aislop/config.yaml` is authoritative for thresholds.

## Root files

`pyproject.toml` (the package map — see the top of this document) · `alembic.ini`
(`script_location = infra/alembic`; its `sqlalchemy.url` is a placeholder, the real
target comes from `agentaudit migrate --db`) · `uv.lock` (generated) · `CLAUDE.md` ·
`AGENTS.md` (the same guidance for Codex) · `README.md` · `CONTRIBUTING.md` ·
`SECURITY.md` · `LICENSE`.

## Never edit by hand

`dist/` · `agentaudit.egg-info/` · `.venv/` · `agentaudit.db` · `**/__pycache__/` ·
`.qlty/out/` · `uv.lock` (regenerate with `uv lock`) · `docs/diagrams/*.svg` (rendered
from the `.d2` sources beside them).

> A stale `agentkit.db` sits at the repo root from before the `agentaudit` rename. The
> live default is `database/agentaudit.db` (`cli.py:DEFAULT_DB_PATH`); the root file is
> leftover state, not a fixture.

---

# Part 2 — Phases and pushes

Each **phase** is a coherent capability. Each **push** is one feature that shipped on its
own branch. Branch names are the real ones from history where they exist.

---

## Phase 0 — The black-box core

*Build a thing that can call an agent, watch what it did, and score it.* Twenty-one
sequential pushes, each one branch, each with a contract spec in `docs/specs/`.

| # | Push | Branch | Landed |
| --- | --- | --- | --- |
| 0.1 | Result/test/run Pydantic models | `feat/schema` | `core/schema.py` |
| 0.2 | Evidence redactor + privacy policy | `feat/redaction` | `core/redaction.py` |
| 0.3 | Target config + validation | `feat/config` | `core/config.py`, `agentaudit/config/` |
| 0.4 | `CallableAgent` + `HTTPAgent` + factory | `feat/agent-adapter` | `core/agent.py` |
| 0.5 | HTTP/callable parity proof | `feat/http-verify` | `tests/test_http_agent.py` |
| 0.6 | Sandbox interface, snapshots, diffs, events | `feat/sandbox-core` | `core/sandbox.py` |
| 0.7 | Treasury sandbox: bank, invoices, approvals | `feat/sandbox-treasury` | `domains/treasury/` |
| 0.8 | Email sandbox: inbox, contacts, outbound | `feat/sandbox-email` | `domains/email/` |
| 0.9 | Assertion registry + built-ins | `feat/assertions` | `core/assertions.py` |
| 0.10 | YAML/JSON/Python test loading | `feat/test-loader` | `core/loader.py` |
| 0.11 | Execution lifecycle | `feat/runner` | `core/runner.py` |
| 0.12 | Category scores, risk weights, thresholds | `feat/scoring` | `core/scoring.py` |
| 0.13 | SQLite persistence | `feat/store` | `core/store.py` |
| 0.14 | Universal black-box pack | `feat/test-packs-core` | `packs/core/` |
| 0.15 | Treasury + email starter packs | `feat/test-packs-domain` | `packs/treasury/`, `packs/email/` |
| 0.16 | `run`/`report`/`ui` with CI exit codes | `feat/cli` | `cli.py` |
| 0.17 | JSON/JUnit/HTML/Markdown export | `feat/reports` | `reports/` |
| 0.18 | FastAPI + Jinja dashboard | `feat/web-ui` | `web/app.py` |
| 0.19 | Run/version comparison + CLI/UI wiring | `feat/regressions` | `core/regressions.py` |
| 0.20 | README quickstart + architecture doc | `feat/docs-demo` | `docs/architecture.md` |
| 0.21 | Agents/tests/authoring pages, sidebar nav | `feat/agents-management-pages` | `web/templates/` |

**Outcome:** call an agent, assert on words *and* actions, score, persist, report.

### Phase 0-fix — the first hardening pass

Six numbered fixes (F1–F6) after the first real look at the code:

| Push | Fixed |
| --- | --- |
| F1 | Test collection unblocked after `examples/` deletion |
| F2 | Numeric scalars redacted in evidence (`fix/f2-redact-numeric-scalars`) |
| F3 | Redaction consolidated to **one** point, in the runner (`fix/f3-single-redaction-point`) |
| F4 | Ruff lint gate added, findings fixed (`fix/f4-ruff-lint-gate`) |
| F5 | Timeout thread-leak ceiling documented (`fix/f5-timeout-thread-cleanup`) |
| F6 | Web `/runs` target/packs paths constrained to project root (`fix/f6-web-path-guard`) |

F3 and F6 are the load-bearing ones — they set the redaction and path-trust invariants
the rest of the codebase now depends on.

---

## Phase 1 — Compliance and agentic attacks

*Turn a test runner into evidence.*

| Push | Branch | Landed |
| --- | --- | --- |
| Fail-closed evaluator P0 hardening | `phase0a-fail-closed-evaluator` | `core/` + `web/` |
| Multi-turn runner support | `phase0b-multi-turn-runner` | `core/runner.py` |
| Agentic attack packs + EU AI Act report | `phase0c-compliance-slice` | `packs/agentic/`, `core/compliance.py`, `reports/compliance.py` |
| Deliberately vulnerable email agent | `feat/agent-trusting-forwarder` | `domains/email/trusting_forwarder_agent.py` |
| GitHub Actions protection pipelines | — | `.github/workflows/` |
| Infra diagrams | — | `docs/diagrams/` |
| Dashboard redesign, mobile, status badges, settings, harness page | `feat/dashboard-redesign-ui` | `web/` |
| Repo folder restructure (`backend`/`frontend`/`infra` split) | — | `pyproject.toml` package map |

**Outcome:** compliance evidence that fails closed, and a UI that shows it.
**This phase created the four-root package layout** described in Part 1.

---

## Phase 2 — Multi-tenancy (T1–T10)

*One deployment, many orgs, no shared state.*

| # | Push | Branch |
| --- | --- | --- |
| T1 | Alembic migration infrastructure | `feat/t1-migrations-infra` |
| T2 | `org_id` on every row, `Store` scoping | `feat/t2-org-scoping` |
| T5 | Targets and packs become DB rows | `feat/t5-targets-packs-tables` |
| T6 | Keycloak realm | `feat/t6-keycloak-realm` |
| T7 | JWT validation dependency | `feat/t7-jwt-principal` |
| T8 | Every route scoped to the caller's org | `feat/t8-scope-routes` |
| T9 | Authored tests become org-scoped rows, not shared files | `feat/t9-drop-fs-test-write` |
| T10 | One long-lived `Store` instead of a connection per request | `feat/t10-connection-pool` |

T9 is the important one: it removed tenant-controlled filesystem writes entirely.

---

## Phase 3 — Async execution and isolation (T11–T16)

*Runs stop blocking a request, and untrusted agent code stops sharing our process.*

| # | Push | Branch |
| --- | --- | --- |
| T11 | Jobs table with explicit leases | `feat/t11-jobs-table` |
| T12 | Polling worker process | `feat/t12-worker` |
| T13 | Async runs end to end | `feat/t13-async-runs` |
| T14 | Artifacts (canonical key layout) | `feat/t14-artifacts` |
| T15 | Secrets + egress policy (SSRF defense) | `feat/t15-secrets-egress` |
| T16 | Killable run isolation, supervisor-owned sandbox | — (`core/isolation.py`) |
| — | Run worker in a hardened container | `feat/worker-container-isolation` |

**Outcome:** a run is a leased job on a worker, in a hardened container, in a killable
process tree, that cannot reach the metadata service.

**Known ceiling** — recorded in memory and worth repeating: isolation here means
*killability*, not containment. It is spawn-based multiprocessing; cloudpickle plus the
RPC surface leave holes that a real container boundary would close.

---

## Phase 4 — The adaptive layer (W1–W14)

*Stop running the same fixed list at every agent.* This is the product differentiator and
the phase most in flight.

| # | Push | Branch | Landed |
| --- | --- | --- | --- |
| W1 | `AgentProfile`, `TestCatalogEntry`, `HarnessPlan` contracts | `feat/w1-profile-models` | `core/profile.py` |
| W2 | Metadata test catalog with explainable ranking | `feat/w2-test-catalog` | `core/catalog.py` |
| W3+W4 | promptfoo + garak adapters behind one interface | `feat/w3-external-adapters` | `core/adapters.py` |
| W12 | Endpoint discovery + harness planner | `feat/w12-planner` | `core/discovery.py`, `core/planner.py` |
| W14 | Selection rationale in reports and dashboard | `feat/w14-plan-rationale` | `reports/plan.py` |
| — | Report planned tests this run does **not** execute | `fix/plan-external-not-executed` | `reports/plan.py` |

### Phase 4b — Attack surface (T1–T2, adaptive)

| Push | Branch | Landed |
| --- | --- | --- |
| Attack transforms library, adaptive tests guarded against them | `feat/t1-t2-attack-surface` | `core/attacks.py` |
| Adaptive attack ladders + trust packs | `feat/adaptive-ladders-and-trust-packs` | `core/adaptive.py`, `packs/core/jailbreak/`, `packs/agentic/agent_trust/` |
| Attacker-model refinement behind the strategy protocol | same | `core/attacker.py` |
| Judge stop condition, attacker techniques, intent-keyed garak mapping | same | `core/judge.py`, `core/jsonx.py` |

### Phase 4c — Wiring the planner into the hosted path

| Push | Branch | Landed |
| --- | --- | --- |
| Plan every worker run, not only CLI `--plan` runs | `feat/wire-planner-into-run` | `worker.py:execute_job` |

The planner had exactly one caller. `agentaudit run --plan` profiled and persisted a
`HarnessPlan`; the **worker** — the path a hosted deployment actually uses — ran the whole
pack and wrote `plan_json` as NULL, so every hosted run rendered as "launched without a
planner". `execute_job` now discovers, plans, applies, and persists. Discovery runs
through a closure carrying the same redactor and validated endpoint as the graded run, so
the egress decision made once is reused rather than reopened.

**Two honest caveats about this phase:**

1. **"Harness" means `HarnessPlan`, not generated per-agent code.** The planner layer
   exists, is tested, and now runs on both the CLI and worker paths — but it selects from
   a catalog; it does not generate harness code.
2. **Adapters normalize, they do not execute.** `core/adapters.py` maps promptfoo/garak
   reports and generates their config/argv, but `agentaudit` does not spawn either tool.
   Adapter-selected tests are ranked and their invocation generated, then run out of band.
3. **The ladders are format strings.** `attacker.py` and `judge.py` open the
   model-driven seam, but both are **off unless configured** — the default path stays
   deterministic, offline, and free, which is what CI depends on.

---

## Phase 5 — Product polish and hygiene

| Push | Branch |
| --- | --- |
| Repo hygiene files + README rewritten for fast evaluation | `docs/readme-and-hygiene` |
| Test any agent by URL; HTTP target fixes | `feat/test-any-endpoint` |
| Remove the stale `examples/` directory and its references | `chore/remove-stale-examples` |
| Fix ruff violations and enforce lint in CI | `chore/fix-lint-and-enforce-in-ci` |
| qlty pre-push hook | `chore/qlty-setup` |
| Rename `agentkit` → `agentaudit` | `rename/agentaudit` |
| Per-test progress during `agentaudit run` | `feat/cli-run-progress` |
| Document how the harness runs a test in isolation | `docs/isolation` |

`examples/` was removed rather than fixed: it was never wired into CI, so it rotted
unnoticed. The `agentaudit run ...` commands in `CLAUDE.md` are the maintained way to
exercise the tool by hand. Do not reintroduce example scripts without a CI job.

---

## What is not built yet

Straight from [`docs/IMPLEMENTATION-TESTS-PLAN.md`](IMPLEMENTATION-TESTS-PLAN.md), with
the current state honestly marked:

| Workstream | Status |
| --- | --- |
| W1–W4 core refactor, catalog, promptfoo, garak | Shipped (adapters normalize only) |
| W5 `inspect_ai` bridge | Not started |
| W6 mini-eval format + scorer library | Not started |
| W7 `ToolEmu`-style `ToolSurface` + simulator templates | Not started |
| W8 `AgentDojo` injection harnesses, defense metadata, replay | Partial — packs exist, no defense comparison mode |
| W9 `tau2-bench` `PolicyBundle` + user simulators | Not started |
| W10 Browser agents (`BrowserGym`/`AgentLab`) | Not started |
| W11 `PurpleLlama` / CWE / ATT&CK mapping | Not started |
| W12 Discovery + planning | Shipped, and wired into both the CLI and worker run paths |
| W13 Iterative attack engine (branch-and-retry, exploit confirmation) | Partial — ladders and transforms ship; branching and reproduction do not |
| W14 Reporting and product surface | Shipped |

The two largest gaps between the current repo and the stated product vision:
**adapter execution** (W3/W4 tail) and **branch-and-retry with exploit confirmation**
(W13).

---

## Working conventions

- **One feature, one branch, one spec.** Phase 0 pushes each have a `docs/specs/*.md`
  contract. Later phases carry the reasoning in module docstrings — read the top 15
  lines of any `core/` module before changing it; they explain *why*, not what.
- **Validation ladder.** Closest test → `bash tools/validate.sh --affected` →
  full suite → `bash tools/validate.sh`. Full suite is ~150s; prefer `--affected` while
  iterating.
- **On Windows, call pytest as a module** (`python -m pytest`). The console-script form
  under `uv run` fails with a trampoline error. CI on Linux uses the script form fine.
- **Dependency direction never reverses.** `cli`/`web` → `core` + `reports` + `domains`;
  `reports` → `core`; `domains` → `core.sandbox`. `core` imports nothing from the others.
