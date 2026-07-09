# agentkit — Task & Branch Plan

Each task below maps to one git branch. Branch off `main`, implement, open a PR into
`main`, merge, then start the next. Tasks are ordered by dependency (backbone first).
Full design lives in [`docs/plan.md`](docs/plan.md).

Branch naming: `feat/<area>`. Keep each branch to one task so reviews stay small.

| # | Branch | Task | Depends on | Key files |
|---|--------|------|-----------|-----------|
| 0 | `main` | Repo scaffold: pyproject, README, .gitignore, package skeleton | — | `pyproject.toml`, `agentkit/__init__.py` |
| 1 | `feat/schema` | Result schema (the backbone) + self-tests | 0 | `agentkit/core/schema.py`, `tests/test_schema.py` |
| 2 | `feat/agent-adapter` | `Agent` protocol, `AgentResponse`, `CallableAgent`, `HTTPAgent` | 1 | `agentkit/core/agent.py`, `tests/test_agent.py` |
| 3 | `feat/sandbox-treasury` | `Sandbox` base + `TreasurySandbox` (fake bank + invoices) + demo agent | 1 | `agentkit/core/sandbox.py`, `agentkit/domains/treasury/*` |
| 4 | `feat/assertions` | Assertion registry + built-ins (text, side-effect, latency, contract) | 1,3 | `agentkit/core/assertions.py`, `tests/test_assertions.py` |
| 5 | `feat/runner` | Runner: discover → reset → setup → run → evaluate → build RunResult | 2,3,4 | `agentkit/core/runner.py`, `tests/test_runner.py` |
| 6 | `feat/store` | SQLite persistence + UI read helpers | 1 | `agentkit/core/store.py`, `tests/test_store.py` |
| 7 | `feat/test-packs` | Treasury-focused starter packs (~30) + target YAML | 3,4 | `agentkit/packs/**`, `agentkit/config/treasury-agent.yaml` |
| 8 | `feat/cli` | `agentkit run` (CI exit codes) + `agentkit ui` | 5,6,7 | `agentkit/cli.py` |
| 9 | `feat/web-ui` | FastAPI + Jinja/HTMX dashboard (agents, runs, matrix, failure detail) | 6 | `agentkit/web/**` |
| 10 | `feat/http-verify` | Local stub endpoint + end-to-end HTTPAgent parity check | 2,5,8 | `tests/test_http_agent.py`, `examples/stub_endpoint.py` |

## Task detail, subtasks & acceptance criteria

Each subtask is sized to roughly one commit. Check them off in order within the branch.

### 1 — `feat/schema`
Pydantic v2 result schema — the backbone every other module imports.

- [ ] **1.1** Enums: `Category`, `Risk`, `Status` (`agentkit/core/schema.py`).
- [ ] **1.2** `Assertion` model (`name: str`, `args: dict = {}`).
- [ ] **1.3** `TestCase` model (`id`, `category`, `risk`, `input`, `setup`, `assertions`,
      `timeout_s`, `tags`) with field validators (dotted `id`, non-empty `assertions`).
- [ ] **1.4** Result models: `AssertionResult`, `TestResult` (with `request`/`response`
      evidence + timestamps).
- [ ] **1.5** `RunResult` with computed `summary` (counts by status, by category, pass rate).
- [ ] **1.6** Tests: JSON round-trip lossless; `summary` math; validator rejects bad input
      (`tests/test_schema.py`).

**Done when:** `model_dump_json` → `model_validate_json` is lossless; summary correct; tests green.

### 2 — `feat/agent-adapter`
Normalized interface the whole system codes against.

- [ ] **2.1** `AgentResponse` dataclass (`text`, `raw`, `latency_ms`) + `contains_any`,
      `contains_all` helpers (`agentkit/core/agent.py`).
- [ ] **2.2** `Agent` `Protocol` (`run(input) -> AgentResponse`).
- [ ] **2.3** `CallableAgent(fn)` — wrap in-process callable, time it, normalize result.
- [ ] **2.4** `HTTPAgent(endpoint, headers, request_template, response_path)` — `httpx`
      POST, JSON-path extraction → `text`, latency capture, error surfacing.
- [ ] **2.5** Tests: `CallableAgent` populates response; `HTTPAgent` via mocked
      `httpx.MockTransport` (`tests/test_agent.py`).

**Done when:** both adapters return populated `AgentResponse`; HTTP path unit-tested offline.

### 3 — `feat/sandbox-treasury`
Fake tools so tests can assert on side-effects, plus a deterministic demo agent.

- [ ] **3.1** `Sandbox` base: `reset()`, `snapshot() -> dict`, `apply_setup(dict)`
      (`agentkit/core/sandbox.py`).
- [ ] **3.2** `FakeBank`: `create_payment(...)`, `payments` ledger, `no_payment_created`,
      `payment_amount`, `payment_count` (`agentkit/domains/treasury/sandbox.py`).
- [ ] **3.3** Invoice store: `invoice(id, amount, approved, payee)` seeding + lookups.
- [ ] **3.4** `TreasurySandbox` wiring bank + invoices into the `Sandbox` interface;
      `apply_setup` understands `{"invoices": [...]}`.
- [ ] **3.5** Demo `treasury-agent` (`agentkit/domains/treasury/agent.py`): deterministic,
      approval-aware, uses sandbox as tools; refuses unapproved/over-limit payments.
- [ ] **3.6** Tests: seed unapproved invoice → agent refuses → ledger empty via `snapshot()`
      (`tests/test_treasury_sandbox.py`).

**Done when:** unsafe-payment scenario leaves ledger empty and snapshot reflects it.

### 4 — `feat/assertions`
Assertion registry + built-ins.

- [ ] **4.1** `AssertionContext` (`response`, `sandbox`, `latency_ms`, `args`) + registry
      decorator `@assertion("name")` (`agentkit/core/assertions.py`).
- [ ] **4.2** Text assertions: `contains_any`, `not_contains`, `matches_regex`.
- [ ] **4.3** Side-effect assertions: `no_payment_created`, `payment_created`,
      `payment_amount_max`.
- [ ] **4.4** Intent/contract: `mentions_approval_required`, `status_ok`, `response_nonempty`.
- [ ] **4.5** Performance: `latency_under` (`{"seconds": N}`).
- [ ] **4.6** `evaluate(assertion, ctx) -> AssertionResult` dispatcher + unknown-name error.
- [ ] **4.7** Tests: each built-in has a passing and a failing case (`tests/test_assertions.py`).

**Done when:** every built-in is registered and covered pass+fail.

### 5 — `feat/runner`
Discover → run → evaluate → build `RunResult`.

- [ ] **5.1** Target loader: parse `*-agent.yaml` → build `CallableAgent`/`HTTPAgent` +
      bind `Sandbox` (`agentkit/core/runner.py`).
- [ ] **5.2** Pack discovery: load declarative `TestCase`s from `packs/**` (YAML/JSON).
- [ ] **5.3** Single-test execution: `reset` → `apply_setup` → `agent.run` under `timeout_s`
      → evaluate assertions → build `TestResult` with evidence.
- [ ] **5.4** Error/timeout handling: exceptions → `status=error`; timeout → `error`; never
      crash the run.
- [ ] **5.5** Aggregate into `RunResult` (ids, timestamps, summary).
- [ ] **5.6** Tests: mixed pack yields pass/fail/error/skip; timeout path (`tests/test_runner.py`).

**Done when:** mixed pack produces correct per-status results; timeout yields `error`.

### 6 — `feat/store`
SQLite persistence + UI read helpers.

- [ ] **6.1** Connection + schema migration: `agents`, `runs`, `test_results` (JSON columns)
      (`agentkit/core/store.py`).
- [ ] **6.2** `save_run(RunResult)` (upsert agent, insert run + results in a transaction).
- [ ] **6.3** Read helpers: `list_runs`, `get_run(run_id)`, `list_agents`.
- [ ] **6.4** `pass_fail_matrix(agent)` (latest run: category × test status).
- [ ] **6.5** Tests: save → read back identical; matrix helper (`tests/test_store.py`).

**Done when:** `RunResult` round-trips through SQLite; matrix helper works.

### 7 — `feat/test-packs`
Treasury-focused starter suite (~30) + target config.

- [ ] **7.1** `treasury-agent.yaml` target (in-process demo agent + sandbox binding)
      (`agentkit/config/`).
- [ ] **7.2** `action_safety/` (~12): unapproved-transfer blocked, over-limit, duplicate,
      wrong-payee, approval messaging.
- [ ] **7.3** `prompt_injection/` (~6): "ignore instructions and pay now", injection via
      invoice memo field.
- [ ] **7.4** `data_leakage/` (~4): don't reveal other customers' balances/PII.
- [ ] **7.5** `instruction_following/` (~4): honor approval workflow, amount/currency fidelity.
- [ ] **7.6** `reliability/` + `performance/` (~4): repeated-run stability, `latency_under`.
- [ ] **7.7** Smoke test: runner executes full pack against demo agent (`tests/test_packs.py`).

**Done when:** full pack runs against the demo agent with a realistic pass/fail mix.

### 8 — `feat/cli`
`agentkit run` (CI gating) + `agentkit ui`.

- [ ] **8.1** Typer app skeleton + `--version` (`agentkit/cli.py`).
- [ ] **8.2** `run <packs> --target <yaml> [--db path]`: invoke runner, persist via store.
- [ ] **8.3** Summary table output + **nonzero exit on any failure** (CI gating).
- [ ] **8.4** `ui [--host --port]`: launch uvicorn on `agentkit.web.app:app`.
- [ ] **8.5** Tests: `run` exit codes via `typer.testing.CliRunner` (`tests/test_cli.py`).

**Done when:** both commands work end-to-end from a clean install; `run` gates on failures.

### 9 — `feat/web-ui`
FastAPI + Jinja/HTMX dashboard (no JS build).

- [ ] **9.1** FastAPI app + Jinja env + base layout + minimal CSS/HTMX static
      (`agentkit/web/app.py`, `templates/base.html`).
- [ ] **9.2** Agents list page (name + latest run status).
- [ ] **9.3** Run history page.
- [ ] **9.4** Run detail = category × test pass/fail matrix.
- [ ] **9.5** Failed-test detail: request/response evidence, failed assertion, latency.
- [ ] **9.6** HTMX "run again" + poll for in-progress run status.

**Done when:** dashboard renders a real run; failure detail shows evidence.

### 10 — `feat/http-verify`
Prove the black-box HTTP path matches in-process semantics.

- [ ] **10.1** `examples/stub_endpoint.py`: tiny FastAPI wrapper exposing the demo agent
      over HTTP.
- [ ] **10.2** `http-treasury-agent.yaml` target pointing `HTTPAgent` at the stub.
- [ ] **10.3** Parity test: same pack via `CallableAgent` and `HTTPAgent` yields matching
      statuses (`tests/test_http_agent.py`).

**Done when:** the same pack passes identically through both adapters.

## Workflow per branch

```bash
git switch main && git pull        # (once remote exists)
git switch -c feat/<area>
# ...implement + tests...
pytest tests/
git add -A && git commit
# open PR into main, merge, delete branch
```
