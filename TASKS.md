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

## Task detail & acceptance criteria

### 1 — `feat/schema`
Pydantic v2 models: `Category`, `Risk`, `Status` enums; `Assertion`, `TestCase`,
`AssertionResult`, `TestResult`, `RunResult` (with computed `summary`).
**Done when:** JSON round-trip (`model_dump_json` → `model_validate_json`) is lossless;
`RunResult.summary` reports counts by status/category and pass rate. Tests green.

### 2 — `feat/agent-adapter`
`AgentResponse` (`text`, `raw`, `latency_ms`, `contains_any`) and `Agent` protocol.
`CallableAgent(fn)` for in-process; `HTTPAgent(endpoint, headers, request_template,
response_path)` using `httpx`, records latency, maps JSON path → `text`.
**Done when:** `CallableAgent` returns a populated `AgentResponse`; `HTTPAgent` unit-tested
against a mocked transport.

### 3 — `feat/sandbox-treasury`
`Sandbox` base (`reset()`, `snapshot() -> dict`). `TreasurySandbox` with `FakeBank`
(`create_payment`, `payments` ledger, `no_payment_created`, `payment_amount`) and invoice
store (`invoice(id, amount, approved)`). Deterministic in-process demo treasury agent that
uses the sandbox as its tools.
**Done when:** seeding an unapproved invoice + asking the demo agent to pay leaves the
ledger empty and `snapshot()` reflects it.

### 4 — `feat/assertions`
Registry `name -> callable(ctx) -> AssertionResult`; `ctx` exposes `response`, `sandbox`,
`latency_ms`, `args`. Built-ins: `contains_any`, `not_contains`, `matches_regex`,
`no_payment_created`, `payment_created`, `payment_amount_max`, `mentions_approval_required`,
`latency_under`, `status_ok`, `response_nonempty`.
**Done when:** each built-in has a passing and failing test.

### 5 — `feat/runner`
`run(target, packs) -> RunResult`. Per test: `sandbox.reset()`, apply `setup`,
`agent.run(input)` under `timeout_s`, evaluate assertions, capture request/response +
latency. Exceptions → `status=error` (run never crashes).
**Done when:** a mixed pack yields pass/fail/error/skip correctly; timeout produces `error`.

### 6 — `feat/store`
SQLite (`sqlite3`): `agents`, `runs`, `test_results` (JSON columns). Read helpers:
list runs, run detail, latest pass/fail matrix per agent.
**Done when:** persist a `RunResult` then read it back identically; matrix helper works.

### 7 — `feat/test-packs`
~30 declarative `TestCase`s: action_safety (~12), prompt_injection (~6), data_leakage (~4),
instruction_following (~4), reliability/performance (~4). Plus `treasury-agent.yaml` target.
**Done when:** `runner` executes the full pack against the demo agent with a realistic
mix of pass/fail.

### 8 — `feat/cli`
`agentkit run <packs> --target <yaml>` → runs, persists, prints summary table, **nonzero
exit on any failure** (CI gating). `agentkit ui` → launches uvicorn.
**Done when:** both commands work end-to-end from a clean install.

### 9 — `feat/web-ui`
FastAPI + Jinja/HTMX: Agents list, Run history, Run detail (category × test matrix),
Failed-test detail (request/response evidence, failed assertion, latency). No JS build.
**Done when:** dashboard renders a real run; failure detail shows evidence.

### 10 — `feat/http-verify`
Tiny local stub endpoint (`examples/stub_endpoint.py`) + test proving `HTTPAgent` runs the
same packs with identical semantics to the in-process path.
**Done when:** same pack passes via both `CallableAgent` and `HTTPAgent`.

## Workflow per branch

```bash
git switch main && git pull        # (once remote exists)
git switch -c feat/<area>
# ...implement + tests...
pytest tests/
git add -A && git commit
# open PR into main, merge, delete branch
```
