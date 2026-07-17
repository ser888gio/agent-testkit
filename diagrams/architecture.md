# Software Architecture Documentation

Project: **agentkit** — black-box testing kit for AI agents.
Source of truth: code as of branch `phase0c-compliance-slice` (verified by reading every module; docs/specs treated as hints only).

## Overview

agentkit is a **layered pipeline library with two thin delivery shells** (a Typer CLI and a FastAPI dashboard) over a shared core. A run is a pure pipeline: `pack YAML → loader → runner (agent adapter + sandbox) → assertions → scoring → SQLite store → reports/web`. Key tech: Python 3.10+, Pydantic v2 (all core models), Typer, FastAPI + Jinja2, httpx, PyYAML, SQLite (stdlib `sqlite3`). Extensibility is registry/adapter based: pluggable sandboxes, pluggable assertions, pluggable report renderers, and two agent adapters behind one `Agent` protocol.

## System Context

- **Developer / CI** drives the system via the `agentkit` CLI (`run`, `report`, `compare`, `ui`). CI gates on the process exit code (`--fail-under`, `--block-on-critical`).
- **Browser user** views persisted runs via the FastAPI dashboard (`agentkit ui`, uvicorn on 127.0.0.1:8000). A token-protected `POST /runs` can re-trigger runs.
- **Target agent under test** is external: either an HTTP endpoint (`HTTPAgent` via httpx) or an in-process Python callable (`CallableAgent`, imported from `module:factory`). Examples in `examples/` (demo_agent, stub_endpoint) play this role for demos/tests.
- **Sandboxes are fakes, not integrations**: the fake bank and fake inbox live in-process; no real external services are touched during a run.

## Layers / Services

### Core engine — `agentkit/core/`
The domain-agnostic pipeline. Every other package depends on it; it depends on nothing else in the repo.

- **`schema.py`** — Purpose: the shared Pydantic models everything imports: `Category` (9 values), `Risk`, `Status`, `Assertion`, `TestCase` (enforces exactly one of `input` XOR `turns`, dotted-lowercase ids, non-empty assertions), `AssertionResult`, `TestResult`, `RunResult`. Dependency root of the core package.
- **`config.py`** — Purpose: target configuration. `TargetConfig` = agent spec (`CallableSpec` | `HTTPSpec`, Pydantic discriminated union on `type`) + optional sandbox name + `EvidencePolicy`. `load_target()` parses YAML/JSON, interpolates `${ENV_VAR}` (fails loudly if unset), validates sandbox name against `KNOWN_SANDBOXES = ("treasury", "email")`.
- **`loader.py`** — Purpose: test discovery. `discover(root)` walks a pack directory for `*.yaml|yml|json` (declarative `TestCase`s) and `test_*.py` modules (`PythonTestCase`: any `def test_*(agent, sandbox)` function, metadata via `@meta` decorator). Validates assertion names against the assertion registry at load time and rejects duplicate test ids. `filter_tests()` filters by tags/categories/ids.
- **`agent.py`** — Purpose: the adapter layer. `Agent` is a `Protocol` with one method `run(input) -> AgentResponse`. Two adapters: `CallableAgent` (wraps a Python callable; passes `sandbox=` if the function's signature accepts it — this is how demo agents get tool access) and `HTTPAgent` (httpx request with `{{ input }}` template rendering and JSON-path response extraction). `build_agent()` is the factory dispatching on the config spec type. Adapters never raise; errors become `AgentResponse.error`.
- **`sandbox.py`** — Purpose: the sandbox plugin contract. Abstract `Sandbox` (reset / apply_setup / snapshot / diff / event recording) plus a module-level registry: `@register_sandbox("name")` + `build_sandbox(name)`. Deliberately knows nothing about payments or mail.
- **`assertions.py`** — Purpose: assertion registry + 14 built-ins. `@assertion("name")` registers a pure function of `AssertionContext` (response, sandbox, latency, diff, args). Generic checks (`contains_any`, `not_contains`, `matches_regex`, `is_valid_json`, `status_ok`, `latency_under`, …) and side-effect checks that duck-type onto sandbox attributes (`getattr(sandbox, "bank"/"inbox", None)`): `payment_created`, `no_payment_created`, `payment_amount_max`, `mail_sent`, `no_mail_sent_to`, `no_external_forward`. Unknown assertion or an assertion exception → failed result, never a raise.
- **`runner.py`** — Purpose: execution lifecycle, "never crashes" invariant. `run(target, tests)` builds sandbox + agent, iterates tests, returns `RunResult`. `run_one()` per test: sandbox reset → `apply_setup` → snapshot before → execute turn(s) with a per-test thread-pool timeout → snapshot after + diff → evaluate assertions → derive status → redact all evidence. **Multi-turn support** (recent): `test.turns` runs each turn sequentially *without* resetting the sandbox, so poisoned memory/state carries across turns; assertions run against the final turn's response. On timeout the sandbox diff is discarded (worker thread may still be mutating state). `_run_python_test()` executes `PythonTestCase` functions, mapping `AssertionError` to failed.
- **`redaction.py`** — Purpose: evidence hygiene. `Redactor` masks built-in patterns (api keys, bearer tokens, emails, IBANs, cards, account numbers, phones) plus config literals/regexes. `EvidencePolicy` controls whether request/response evidence is stored at all. Runner redacts *before* results leave the pipeline (project invariant: never store/render raw evidence).
- **`scoring.py`** — Purpose: `score(RunResult) -> ScoreReport`. Risk-weighted overall score (low=1 … critical=8), per-category scores, critical-failure count, CI gate (`fail_under` threshold + block-on-critical). **Fails closed**: an empty or all-skipped run scores 0.0 with `gate_passed=False, incomplete=True`.
- **`regressions.py`** — Purpose: `compare(before, after, scores) -> RunDiff` — newly failing/passing, added/removed, latency deltas, score deltas, critical regressions. Powers `agentkit compare` and the web `/compare` page.
- **`store.py`** — Purpose: SQLite persistence. Three tables: `agents`, `runs` (summary + score JSON), `test_results` (full result JSON per row). Applies the evidence policy/redaction again on save. Read helpers (`list_runs`, `get_run`, `pass_fail_matrix`) serve both CLI and web.
- **`compliance.py`** — Purpose (recent feature): pure data mapping from test results to regulatory controls. EU AI Act articles / ISO 42001 / NIST AI RMF are inherited from `Category` alone (`CONTROLS_BY_CATEGORY`); the OWASP Agentic (ASI) code is refined from the test-id's pack segment (`OWASP_BY_PACK`: goal_hijack→ASI01, tool_misuse→ASI02, privilege_abuse→ASI03, code_execution→ASI05, memory_poisoning→ASI06, human_oversight→ASI09). `UNCOVERED` lists ASI codes not black-box testable (04/07/08/10), surfaced as explicit gaps. No rules engine, no LLM.

### Domain sandboxes — `agentkit/domains/`
Plugin implementations of `Sandbox`, plus deterministic demo agents used as reference targets.

- **`treasury/sandbox.py`** — `@register_sandbox("treasury")` `TreasurySandbox`: `FakeBank` (payment ledger, `payment_count`/`payment_amount` queried by assertions) + invoice store; records `payment.created` events.
- **`treasury/agent.py`** — deterministic regex-based demo agent: pays only approved, unpaid, within-limit invoices to the right payee/account; used by `agentkit/config/treasury-agent.yaml` as a callable target.
- **`email/sandbox.py`** — `@register_sandbox("email")` `EmailSandbox`: fake inbox (messages), contacts, outbound `SentMail` ledger, internal-domain check (`is_external`) used by `no_external_forward`.
- **`email/agent.py`** — deterministic demo triage agent refusing exfiltration/phishing/injection.
- **`email/fixtures.py`** — reusable malicious/benign setup dicts (exfiltration, phishing) for tests and packs.

Registration is import-side-effect based, so **both entry points eagerly import the domain sandbox modules** (`cli.py` and `web/app.py` top-of-file `import agentkit.domains.*.sandbox # noqa: F401`) before `build_sandbox` can run.

### Test packs — `agentkit/packs/`
Declarative YAML content, not code (one exception: `core/_demo_safe_agent.py`, a helper for the core pack).

- **core/** — endpoint_contract, prompt_injection, data_leakage, performance, reliability, robustness.
- **treasury/** — 6 packs: approved_payment, unapproved_payment, over_limit, duplicate_payment, wrong_payee, changed_bank_details.
- **email/** — exfiltration, phishing, unauthorized_forward.
- **agentic/** (recent) — 6 attack packs mapped to OWASP ASI codes: tool_misuse, memory_poisoning (uses multi-turn `turns:`), goal_hijack, privilege_abuse, human_oversight, code_execution.

### Reports — `agentkit/reports/`
Renderer registry: `render(run, score, fmt)` dispatches on a dict of `(RunResult, ScoreReport) -> str` functions.

- `json.py`, `junit.py` (CI), `html.py`, `md.py` (humans), and `compliance.py` / `compliance-json` (recent): rolls results up by EU AI Act article via `core/compliance.controls_for`, lists OWASP coverage and explicit `UNCOVERED` gaps, and leads with a legal disclaimer ("readiness evidence, not a conformity determination"). No new redaction path — evidence arrives already redacted.

### CLI — `agentkit/cli.py`
Typer app; the primary entry point (`agentkit` console script). Commands wire the core pipeline together; no business logic of its own beyond the table printer. Exit codes: 0 pass, 1 gate blocked / critical regression, 2 config/loader error.

### Web dashboard — `agentkit/web/app.py`
FastAPI + Jinja2 templates (server-rendered, no JS build), read-mostly views over `Store`. Security hardening (recent P0 work): the `POST /runs` re-run route requires a per-process access token (`AGENTKIT_WEB_TOKEN` or generated secret) and only accepts target/pack paths resolving under `agentkit/config/` or `agentkit/packs/` — so the route can't be coaxed into importing arbitrary Python callables.

### Examples & tests
- `examples/` — `demo_agent.py`, `run_treasury.py`, `run_email.py` (programmatic pipeline usage), `stub_endpoint.py` (FastAPI stub target for HTTP-adapter demos).
- `tests/` — 23 pytest files mirroring core modules 1:1, plus `test_packs_core.py`/`test_packs_domain.py` (packs run against demo agents), `test_security_p0.py` (fail-closed scoring + web hardening), shared fixtures in `_fixtures.py`.

## Dependency Graph (verified from imports)

```
cli.py ──────────┐
web/app.py ──────┤──> core/{config, loader, runner, scoring, store, regressions}
reports/* ───────┤──> core/{schema, scoring, compliance}
domains/*/sandbox ──> core/sandbox          (register via decorator)
domains/*/agent ────> domains/*/sandbox
core/runner ────> core/{agent, assertions, config, loader, redaction, sandbox, schema}
core/loader ────> core/{assertions, schema}
core/store ─────> core/{config, redaction, schema, scoring}
core/compliance ──> core/schema
```

Direction is strictly inward: shells → core; domains → core; core → nothing internal. External libs: pydantic (models everywhere), httpx (agent.py only), yaml (config, loader), typer (cli), fastapi/jinja2/uvicorn (web), sqlite3 stdlib (store).

## Data Flow

### Flow 1: `agentkit run <packs> --target <yaml>` (test execution)

1. `cli.run_cmd` → `config.load_target()`: parse YAML, interpolate env vars, validate into `TargetConfig`.
2. `loader.discover(packs_dir)`: collect YAML/JSON test cases + `test_*.py` functions; validate ids and assertion names; `filter_tests()` by `--tag`/`--category`.
3. `runner.run()`: `build_sandbox(target.sandbox)` from the registry, `build_agent(target)` (callable import or HTTP spec).
4. Per test (`run_one`): sandbox `reset()` → `apply_setup(test.setup)` → `snapshot()` before → agent `run()` per turn under a thread-pool timeout (multi-turn: no reset between turns) → `snapshot()` after → `diff()`.
5. `assertions.evaluate()` each assertion against `AssertionContext` (response text + sandbox side-effects + latency + diff).
6. Status derived (error > skip > pass/fail); request/response/diff/assertion details pass through `Redactor` before entering `TestResult`.
7. `scoring.score()` → risk-weighted `ScoreReport` + gate decision.
8. `Store.save_run()` persists agents/runs/test_results rows to `agentkit.db` (redacting again per evidence policy).
9. Output: table or `--format json`; optional `--compliance` appends the compliance report; process exits 0/1 on gate.

### Flow 2: Dashboard viewing (`agentkit ui`)

1. `cli.ui_cmd` starts uvicorn serving `agentkit.web.app:app`.
2. `GET /` → `Store.list_runs(limit=20)` → `dashboard.html`. Drill-down: `/agents` → `/agents/{id}` (runs + pass/fail matrix) → `/runs/{run_id}` (results sorted failures-first, category matrix) → `/runs/{id}/tests/{test_id}` (redacted evidence detail).
3. `GET /compare?a=&b=` loads both runs from the store and renders `regressions.compare()` output.
4. `POST /runs?target=&packs=` (token-gated, path-allowlisted) re-executes Flow 1 steps 1–8 in-process and redirects to the new run page.

### Flow 3: Compliance report generation

1. Either `agentkit run ... --compliance` (fresh run) or `agentkit report --run <id> --format compliance[-json]` (from the store).
2. `reports.render(run, score, "compliance")` → `reports/compliance.to_compliance()`.
3. For each `TestResult`, `core/compliance.controls_for()` resolves controls: EU/ISO/NIST from the category, OWASP ASI code from the test-id's pack segment.
4. Results roll up per EU AI Act article (covered / gaps / not-tested + ISO/NIST refs); untestable ASI codes render as explicit gaps; the disclaimer frames output as readiness evidence, not a conformity determination.

### Flow 4: Multi-turn attack (memory poisoning)

1. A pack test declares `turns: [...]` instead of `input:` (schema enforces XOR).
2. Runner executes turns sequentially against the same agent with **no sandbox reset between turns** — state/poisoned memory persists like a server-side session.
3. The final turn's response feeds the assertions; the sandbox diff spans the whole conversation. A timeout on any turn aborts the loop and discards the diff.

## API Contracts

### CLI (`agentkit`)
| Command | Key options | Exit codes |
|---|---|---|
| `run PACKS --target FILE` | `--db`, `--fail-under`, `--block-on-critical/--no-…`, `--tag`, `--category`, `--format table\|json`, `--compliance` | 0 gate pass, 1 gate block, 2 config/loader error or no tests |
| `report --run ID` | `--format json\|junit\|html\|md\|compliance\|compliance-json`, `--out`, `--db` | 2 unknown run/format |
| `compare RUN_A RUN_B` | `--db` (positional run ids — the `--base/--head` form in CLAUDE.md is outdated; code wins) | 1 if critical regressions |
| `ui` | `--host` (default 127.0.0.1), `--port` (8000), `--db` | — |

### FastAPI routes (`agentkit/web/app.py`)
| Route | Purpose |
|---|---|
| `GET /` | Recent runs dashboard |
| `GET /agents`, `GET /agents/{id}` | Agent list / detail + pass-fail matrix |
| `GET /runs/{run_id}` | Run detail (score, category matrix, results) |
| `GET /runs/{run_id}/tests/{test_id}` | Single test evidence |
| `GET /runs/{run_id}/status` | HTML fragment or JSON (content-negotiated) status poll |
| `POST /runs?target=&packs=` | Token-gated re-run; paths must resolve under `config/` or `packs/` |
| `GET /compare?a=&b=` | Run diff view |
| `/static/*` | Static assets |

### Internal extension contracts
- `Agent` protocol: `run(input: str | dict) -> AgentResponse`.
- Sandbox plugin: subclass `Sandbox`, implement `reset/apply_setup/snapshot`, register with `@register_sandbox(name)` **and** add name to `config.KNOWN_SANDBOXES`.
- Assertion plugin: `@assertion(name)` on `(AssertionContext) -> AssertionResult`.
- Report renderer: `(RunResult, ScoreReport) -> str` in `reports._RENDERERS`.

## Deployment Mapping

- **Single local process, no services to deploy.** `agentkit run` is a short-lived CLI process; target agents are either imported in-process (callable) or reached over HTTP.
- **Dashboard** = one uvicorn process (default loopback `127.0.0.1:8000`), same codebase, same DB file. State-changing route protected by a per-process token.
- **State** = one SQLite file (`agentkit.db`, path via `--db` / `AGENTKIT_DB`), gitignored and safe to delete; there is no migration story beyond `CREATE TABLE IF NOT EXISTS`.
- **CI** = run the CLI, gate on exit code, optionally emit `--format junit` for the CI system.

## Technical Debt / Concerns

1. **Sandbox names are hardcoded twice**: the registry (`sandbox.SANDBOXES`, populated by import side-effect) and `config.KNOWN_SANDBOXES` tuple must agree; a third-party sandbox would pass registration but fail config validation. Registration-by-import also forces the eager `# noqa: F401` imports duplicated in both `cli.py` and `web/app.py`.
2. **Timeout does not kill the worker thread** (`runner._run_with_timeout`, `shutdown(wait=False)`): a hung agent thread lingers and may keep mutating the sandbox; mitigated by discarding the diff, acknowledged in-code as Phase 2 work.
3. **Domain-specific assertions live in core** (`assertions.py` knows about `bank`/`inbox` via `getattr` duck-typing). Works, but core is no longer fully domain-agnostic; growing domains will bloat this file.
4. **Double redaction**: runner redacts evidence into `TestResult`, then `Store.save_run` redacts again. Harmless (idempotent) but suggests unclear ownership of the redaction boundary.
5. **`web/app.py` `POST /runs` executes runs synchronously** in the request thread; a slow pack blocks the server. `/runs/{id}/status` implies a polling story, but runs are never actually in a "running" state in the DB (saved only after completion).
6. **Docs lag code** (confirmed): CLAUDE.md's `compare --base --head` doesn't match the positional-arg implementation; specs predate the agentic packs, multi-turn `turns:`, and `core/compliance.py`.
7. **Minor runner wart**: in `run_one`, `response` is bound only inside the turns loop — safe today because schema guarantees at least one turn, but fragile if that invariant ever loosens.
