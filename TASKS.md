# agentkit — Task & Branch Plan

Each task maps to one git branch. Branch off `main`, implement, open a PR into `main`,
merge, then start the next. Ordered by dependency (backbone first). Full design lives in
[`docs/plan.md`](docs/plan.md); target architecture in
[`docs/architecture.md`](docs/architecture.md) (written in task 20).

Branch naming: `feat/<area>`. One task per branch so reviews stay small. Subtasks are
sized to roughly one commit each.

> **Implementer handoff:** each branch has a full contract spec (public API, data
> models/formats, lifecycle, failure behavior, examples, required tests, observable "done")
> under [`docs/specs/`](docs/specs/README.md). Read your branch's spec before coding — it is
> the source of truth for interfaces and examples so branches don't invent incompatible shapes.

## Branch map

| #  | Branch | Task | Depends on |
|----|--------|------|-----------|
| 0  | `main` | Repo scaffold | — |
| 1  | `feat/schema` | Core result/test/run models | 0 |
| 2  | `feat/redaction` | Evidence redaction + privacy controls | 1 |
| 3  | `feat/config` | Target config module + validation | 1,2 |
| 4  | `feat/agent-adapter` | `CallableAgent` + `HTTPAgent` | 1,3 |
| 5  | `feat/http-verify` | Local HTTP endpoint parity proof | 4 |
| 6  | `feat/sandbox-core` | Generic sandbox interface + snapshots/diffs/events | 1 |
| 7  | `feat/sandbox-treasury` | Fake bank, invoices, approvals, demo treasury agent | 6 |
| 8  | `feat/sandbox-email` | Fake inbox, contacts, outbound mail, demo email agent | 6 |
| 9  | `feat/assertions` | Assertion registry + built-ins | 1,6 |
| 10 | `feat/test-loader` | YAML/JSON/Python test loading + validation | 1,9 |
| 11 | `feat/runner` | Execution lifecycle | 4,6,9,10 |
| 12 | `feat/scoring` | Category scores, risk weights, thresholds | 1,11 |
| 13 | `feat/store` | SQLite persistence | 1,2,12 |
| 14 | `feat/test-packs-core` | Universal black-box tests | 9,10 |
| 15 | `feat/test-packs-domain` | Treasury + email starter packs | 7,8,9,10 |
| 16 | `feat/cli` | `run` / `ui` / `report` commands | 11,12,13 |
| 17 | `feat/reports` | JSON/HTML/JUnit/Markdown export for CI | 12 |
| 18 | `feat/web-ui` | Dashboard | 13,12 |
| 19 | `feat/regressions` | Compare runs / agent versions | 12,13 |
| 20 | `feat/docs-demo` | README walkthrough + example scripts + `docs/architecture.md` | 16,18 |

## Recommended MVP cut

Ship a realistic first working prototype with: **0–7** (schema, redaction, config, adapter,
http, sandbox-core, treasury) → **9–13** (assertions, loader, runner, scoring, store) →
**14** (core tests) → **16** (CLI) → **18** (UI) → **20** (docs demo). Email sandbox (8),
domain packs (15), reports (17) and regressions (19) follow immediately after and are the
strongest differentiators — pull them into the MVP if time allows (email is the most
relatable demo).

---

## Task detail, subtasks & acceptance criteria

### 1 — `feat/schema`
Pydantic v2 result schema — the backbone every other module imports.

- [ ] **1.1** Enums: `Category`, `Risk`, `Status` (`agentkit/core/schema.py`).
- [ ] **1.2** `Assertion` model (`name`, `args`).
- [ ] **1.3** `TestCase` model (`id`, `category`, `risk`, `input`, `setup`, `assertions`,
      `timeout_s`, `tags`) + validators (dotted `id`, non-empty `assertions`).
- [ ] **1.4** Result models: `AssertionResult`, `TestResult` (with `request`/`response`
      evidence + timestamps).
- [ ] **1.5** `RunResult` (ids, agent ref, timestamps, `results`).
- [ ] **1.6** Tests: JSON round-trip lossless; validators reject bad input (`tests/test_schema.py`).

**Done when:** `model_dump_json` → `model_validate_json` is lossless; tests green.

### 2 — `feat/redaction`
Redaction is core, not a nice-to-have — the product tests *private* company agents.

- [ ] **2.1** `Redactor` with built-in patterns: API keys/tokens, emails, account/IBAN
      numbers, card numbers, phone, generic `sk-`/`Bearer` secrets (`agentkit/core/redaction.py`).
- [ ] **2.2** Configurable extra regex patterns + literal secret list.
- [ ] **2.3** `redact(value)` over str/dict/list (recursive) → masked copy.
- [ ] **2.4** `store_evidence: bool` + `redact_evidence: bool` policy object; when evidence
      storage is off, drop request/response bodies entirely.
- [ ] **2.5** Tests: API keys, emails, account numbers, nested payloads redacted; policy
      toggles honored (`tests/test_redaction.py`).

**Done when:** given a payload with secrets, stored evidence contains none of them; policy
flags control storage vs redaction.

### 3 — `feat/config`
Target configs are a real module, not something buried in the runner.

- [ ] **3.1** `TargetConfig` model: `name`, `agent` (`type: callable|http`), `endpoint`,
      `headers`, `timeout_s`, `request_template`, `response_path` (`agentkit/core/config.py`).
- [ ] **3.2** `sandbox` binding (which sandbox + seed) + `evidence`/`redaction` policy
      (reuses task 2) fields.
- [ ] **3.3** Loader: parse YAML/JSON → `TargetConfig`; env-var interpolation for secrets
      (`${ENV_VAR}`) so keys never sit in files.
- [ ] **3.4** Validation with actionable error messages (missing endpoint for http, unknown
      sandbox, bad response_path).
- [ ] **3.5** Tests + example `agentkit/config/treasury-agent.yaml` skeleton
      (`tests/test_config.py`).

**Done when:** a valid YAML loads into a `TargetConfig`; invalid configs raise clear errors.

### 4 — `feat/agent-adapter`
Normalized interface the whole system codes against.

- [ ] **4.1** `AgentResponse` (`text`, `raw`, `latency_ms`, `status`) + `contains_any`/
      `contains_all` (`agentkit/core/agent.py`).
- [ ] **4.2** `Agent` `Protocol` (`run(input) -> AgentResponse`).
- [ ] **4.3** `CallableAgent(fn)` — wrap in-process callable, time it, normalize.
- [ ] **4.4** `HTTPAgent` from `TargetConfig` — `httpx` POST, `request_template` render,
      `response_path` extraction, latency, error surfacing.
- [ ] **4.5** `build_agent(config)` factory dispatching on `agent.type`.
- [ ] **4.6** Tests: `CallableAgent` populates response; `HTTPAgent` via `httpx.MockTransport`
      (`tests/test_agent.py`).

**Done when:** both adapters return populated `AgentResponse`; HTTP path unit-tested offline.

### 5 — `feat/http-verify`
Prove the black-box HTTP path matches in-process semantics.

- [ ] **5.1** `examples/stub_endpoint.py`: tiny FastAPI wrapper exposing a demo agent over HTTP.
- [ ] **5.2** `http-*-agent.yaml` target pointing `HTTPAgent` at the stub.
- [ ] **5.3** Parity test: same input via `CallableAgent` and `HTTPAgent` → matching
      normalized responses (`tests/test_http_agent.py`).

**Done when:** the same input passes identically through both adapters.

### 6 — `feat/sandbox-core`
Generic sandbox behavior, split away from any domain — action-safety is a key differentiator.

- [ ] **6.1** `Sandbox` base: `reset()`, `apply_setup(dict)` (`agentkit/core/sandbox.py`).
- [ ] **6.2** State capture: `snapshot() -> dict`.
- [ ] **6.3** `diff(before, after) -> dict` (added/removed/changed).
- [ ] **6.4** `events` log + `record_event(kind, data)` for side-effect recording
      (tool calls, actions taken).
- [ ] **6.5** Tests with a trivial in-memory sandbox: snapshot/diff/events (`tests/test_sandbox_core.py`).

**Done when:** a sandbox subclass can record side-effects and produce before/after diffs.

### 7 — `feat/sandbox-treasury`
Fake bank + invoices + approvals + deterministic demo treasury agent.

- [ ] **7.1** `FakeBank`: `create_payment(...)`, `payments` ledger, `no_payment_created`,
      `payment_amount`, `payment_count`; records events (`agentkit/domains/treasury/sandbox.py`).
- [ ] **7.2** Invoice store: `invoice(id, amount, approved, payee, bank_details)` + lookups.
- [ ] **7.3** Approval model + payment limits; changed-bank-details detection.
- [ ] **7.4** `TreasurySandbox(Sandbox)` wiring bank + invoices; `apply_setup` seeds invoices.
- [ ] **7.5** Demo treasury agent: approval-aware, refuses unapproved/over-limit/changed-payee
      payments (`agentkit/domains/treasury/agent.py`).
- [ ] **7.6** Tests: unsafe-payment scenarios leave ledger empty via `snapshot()` (`tests/test_treasury.py`).

**Done when:** unapproved/over-limit/wrong-payee requests leave the ledger empty.

### 8 — `feat/sandbox-email`
Fake inbox + contacts + outbound ledger + demo triage agent — the most relatable demo.

- [ ] **8.1** `FakeInbox`: messages, `contacts`, attachments (`agentkit/domains/email/sandbox.py`).
- [ ] **8.2** Outbound `sent` ledger: `send(to, subject, body)`, `forwarded`, helpers
      `no_mail_sent_to`, `mail_count`; records events.
- [ ] **8.3** Malicious email fixtures (exfiltration/phishing/injection vendor mail).
- [ ] **8.4** `EmailSandbox(Sandbox)`; `apply_setup` seeds inbox + contacts.
- [ ] **8.5** Demo email triage agent: summarizes/labels, refuses to forward payroll/PII to
      external addresses (`agentkit/domains/email/agent.py`).
- [ ] **8.6** Tests: malicious "forward payroll" mail → no outbound to attacker (`tests/test_email.py`).

**Done when:** the exfiltration demo leaves the outbound ledger clean.

### 9 — `feat/assertions`
Assertion registry + built-ins.

- [ ] **9.1** `AssertionContext` (`response`, `sandbox`, `latency_ms`, `args`) + `@assertion("name")`
      registry (`agentkit/core/assertions.py`).
- [ ] **9.2** Text: `contains_any`, `not_contains`, `matches_regex`.
- [ ] **9.3** Treasury side-effect: `no_payment_created`, `payment_created`, `payment_amount_max`.
- [ ] **9.4** Email side-effect: `no_mail_sent_to`, `mail_sent`, `no_external_forward`.
- [ ] **9.5** Intent/contract: `mentions_approval_required`, `status_ok`, `response_nonempty`,
      `is_valid_json`.
- [ ] **9.6** Performance: `latency_under` (`{"seconds": N}`).
- [ ] **9.7** `evaluate(assertion, ctx) -> AssertionResult` dispatcher + unknown-name error.
- [ ] **9.8** Tests: each built-in has a passing + failing case (`tests/test_assertions.py`).

**Done when:** every built-in is registered and covered pass+fail.

### 10 — `feat/test-loader`
Test discovery/loading, kept separate from the runner.

- [ ] **10.1** Declarative loader: YAML/JSON files → `TestCase`s, with `tags`, `category`,
      expected sandbox `setup` (`agentkit/core/loader.py`).
- [ ] **10.2** Directory discovery across `packs/**`; stable ordering.
- [ ] **10.3** Basic Python test-module loading (`def test_*(agent, sandbox)`) collected as
      `TestCase`-equivalents.
- [ ] **10.4** Validation errors with useful messages (unknown category/assertion, bad setup).
- [ ] **10.5** Filtering by tag/category/id.
- [ ] **10.6** Tests: load mixed dir, bad file raises actionable error (`tests/test_loader.py`).

**Done when:** a mixed pack directory loads into validated `TestCase`s; bad files fail loudly.

### 11 — `feat/runner`
Execution lifecycle.

- [ ] **11.1** Build agent + sandbox from `TargetConfig` (tasks 3,4,6) (`agentkit/core/runner.py`).
- [ ] **11.2** Per-test: `sandbox.reset()` → `apply_setup` → `agent.run` under `timeout_s`
      → snapshot before/after → evaluate assertions.
- [ ] **11.3** Build `TestResult` with redacted (task 2) request/response evidence + latency.
- [ ] **11.4** Error/timeout handling → `status=error`; run never crashes.
- [ ] **11.5** Aggregate into `RunResult`.
- [ ] **11.6** Tests: mixed pack → pass/fail/error/skip; timeout path (`tests/test_runner.py`).

**Done when:** mixed pack produces correct per-status results; timeout yields `error`.

### 12 — `feat/scoring`
More than pass/fail — what a dashboard and CI gate need.

- [ ] **12.1** `score(run) -> ScoreReport`: overall pass rate (`agentkit/core/scoring.py`).
- [ ] **12.2** Per-category scores.
- [ ] **12.3** Risk-weighted score (weight by `Risk`).
- [ ] **12.4** Critical-failure detection (any failed `critical`-risk test).
- [ ] **12.5** `fail_under` threshold + gate decision (pass/block).
- [ ] **12.6** Tests: known run → expected overall/category/weighted/critical numbers
      (`tests/test_scoring.py`).

**Done when:** a run yields overall %, category %, risk-weighted %, critical count, gate verdict.

### 13 — `feat/store`
SQLite persistence.

- [ ] **13.1** Connection + migration: `agents`, `runs`, `test_results`, `scores`
      (JSON columns) (`agentkit/core/store.py`).
- [ ] **13.2** `save_run(RunResult, ScoreReport)` — applies redaction policy on write.
- [ ] **13.3** Read helpers: `list_runs`, `get_run`, `list_agents`.
- [ ] **13.4** `pass_fail_matrix(agent)` (latest run: category × test status).
- [ ] **13.5** Tests: save → read back identical; matrix helper (`tests/test_store.py`).

**Done when:** run + score round-trip through SQLite; stored evidence honors redaction policy.

### 14 — `feat/test-packs-core`
Universal black-box tests (domain-agnostic).

- [ ] **14.1** `endpoint_contract/`: endpoint health, schema validity, response nonempty.
- [ ] **14.2** Robustness: malformed input, empty input, very long input.
- [ ] **14.3** `prompt_injection/`: instruction override, system-prompt extraction.
- [ ] **14.4** `data_leakage/`: generic secret/PII leakage probes.
- [ ] **14.5** `performance/` + `reliability/`: latency, consistency over repeated runs.
- [ ] **14.6** Smoke test: loader + runner execute the core pack (`tests/test_packs_core.py`).

**Done when:** core pack runs against any agent target without domain assumptions.

### 15 — `feat/test-packs-domain`
Treasury + email starter packs.

- [ ] **15.1** Treasury: unapproved payment, wrong payee, over-limit, changed bank details,
      duplicate payment (`agentkit/packs/treasury/`).
- [ ] **15.2** Email: exfiltration, unauthorized forwarding, phishing detection
      (`agentkit/packs/email/`).
- [ ] **15.3** Target configs for both demo agents (`agentkit/config/`).
- [ ] **15.4** Smoke test: each domain pack runs against its demo agent with a realistic
      pass/fail mix (`tests/test_packs_domain.py`).

**Done when:** both domain packs run end-to-end against their demo agents.

### 16 — `feat/cli`
`run` / `ui` / `report` commands.

- [ ] **16.1** Typer app skeleton + `--version` (`agentkit/cli.py`).
- [ ] **16.2** `run <packs> --target <yaml> [--db]`: load → run → score → persist.
- [ ] **16.3** Summary table + **nonzero exit** on `fail_under`/critical failure (CI gating).
- [ ] **16.4** `report --run <id> --format <json|html|junit|md>` (delegates to task 17).
- [ ] **16.5** `ui [--host --port]`: launch uvicorn.
- [ ] **16.6** Tests: `run` exit codes via `CliRunner` (`tests/test_cli.py`).

**Done when:** all three commands work from a clean install; `run` gates correctly.

### 17 — `feat/reports`
Export for CI + humans.

- [ ] **17.1** JSON report (full run + scores) (`agentkit/reports/`).
- [ ] **17.2** JUnit XML (per-test cases) — CI systems parse it natively.
- [ ] **17.3** HTML summary (scores + failed-test evidence).
- [ ] **17.4** Markdown report (PR-comment friendly).
- [ ] **17.5** Tests: golden-file checks per format (`tests/test_reports.py`).

**Done when:** a run exports valid JSON, JUnit XML, HTML, and Markdown.

### 18 — `feat/web-ui`
FastAPI + Jinja/HTMX dashboard (no JS build).

- [ ] **18.1** App + Jinja base layout + minimal CSS/HTMX static (`agentkit/web/app.py`).
- [ ] **18.2** Agents list (name + latest score/status).
- [ ] **18.3** Run history.
- [ ] **18.4** Run detail: score header + category × test pass/fail matrix.
- [ ] **18.5** Failed-test detail: redacted request/response evidence, failed assertion, latency.
- [ ] **18.6** HTMX "run again" + poll for in-progress status.

**Done when:** dashboard renders a real run with scores; failure detail shows redacted evidence.

### 19 — `feat/regressions`
Compare runs / agent versions — turns the tool into a release-safety system.

- [ ] **19.1** `compare(run_a, run_b) -> Diff`: newly failing / newly passing tests
      (`agentkit/core/regressions.py`).
- [ ] **19.2** Latency deltas per test + overall.
- [ ] **19.3** Score deltas (overall/category/weighted).
- [ ] **19.4** Critical-regression flag (new critical failure).
- [ ] **19.5** CLI `compare <run_a> <run_b>` + UI diff view.
- [ ] **19.6** Tests: constructed run pair → expected diff (`tests/test_regressions.py`).

**Done when:** comparing two runs surfaces new failures/passes, latency + score deltas, and
critical regressions.

### 20 — `feat/docs-demo`
Polished walkthrough + example scripts + architecture doc.

- [ ] **20.1** README quickstart: install → run treasury pack → view UI → export report.
- [ ] **20.2** `examples/` runnable scripts (treasury + email demos).
- [ ] **20.3** `docs/architecture.md`: control plane vs runner; black-box vs instrumented
      modes; privacy/redaction model; sandbox model; "trace visibility" definition; future
      enterprise deployment (customer-hosted runner / VPC).
- [ ] **20.4** Link architecture + plan from README.

**Done when:** a new user can follow the README end-to-end; architecture doc points toward
the future enterprise product.

## Workflow per branch

```bash
git switch main && git pull        # (once remote exists)
git switch -c feat/<area>
# ...implement subtasks (≈one commit each) + tests...
pytest tests/
git add -A && git commit
# open PR into main, merge, delete branch
```
