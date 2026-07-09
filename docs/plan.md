# agentkit — MVP Plan (Python SDK + Result Schema Backbone)

## Context

We're building the first prototype of **agentkit**: a black-box testing kit for AI agents.
The premise is that companies will expose only agent **endpoints** — not prompts, tools,
orchestration, memory, or source — so tests must run against an API boundary and, where
needed, assert on the state of **fake tools/services** the agent was given (e.g. "was a
payment actually created?"). The product should be universal but demo on a high-stakes
vertical first.

This plan builds the **backbone**: the Python `TestCase`/result schema and the SDK
(`Agent` adapter + `Sandbox` interface + runner), wrapped in the smallest runnable MVP —
one demo **treasury/payment** agent, fake services, a SQLite result store, a FastAPI +
Jinja/HTMX dashboard, and a CLI. Everything else (SaaS auth, customer-hosted runners,
multi-agent, OTel, LLM-as-judge) is explicitly out of scope for this version.

Locked decisions (this session):
- **Demo domain:** treasury/payment agent first (single vertical).
- **UI:** FastAPI + Jinja/HTMX (one process, no JS build).
- **Trace depth:** black-box endpoint testing **plus** sandbox side-effect assertions.
- **Name:** `agentkit` (package, CLI, UI title).

Greenfield: working dir `C:\Users\nicas\Desktop\agent-testkti` is empty.

---

## Architecture (MVP)

```
agentkit/
  core/
    schema.py        # TestCase, Assertion, RunResult, TestResult, enums
    assertions.py    # built-in assertion registry (name -> callable)
    agent.py         # Agent adapter: HTTP endpoint + in-process callable
    sandbox.py       # Sandbox base + reset/state protocol
    runner.py        # discover -> run -> evaluate -> persist
    store.py         # SQLite persistence (agents, runs, test_results)
  domains/
    treasury/
      sandbox.py     # TreasurySandbox: fake bank + invoice store
      agent.py       # demo treasury approval agent (in-process, deterministic)
  packs/
    action_safety/   # payment approval, unapproved transfer blocked, limits
    prompt_injection/
    data_leakage/
    instruction_following/
    reliability/
    performance/
  web/
    app.py           # FastAPI app
    templates/       # Jinja: agents, runs, run detail, pass/fail matrix
    static/          # minimal css + htmx
  cli.py             # `agentkit run`, `agentkit ui`
  config/
    treasury-agent.yaml   # target definition (endpoint or in-process ref)
pyproject.toml
tests/                # pytest for agentkit itself (not the agent tests)
```

---

## 1. Result schema — `agentkit/core/schema.py` (the backbone)

Use `pydantic` v2 dataclasses/models for validation + JSON (de)serialization.

- `Category(str, Enum)`: `endpoint_contract, prompt_injection, data_leakage,
  instruction_following, action_safety, tool_use, memory_context, reliability, performance`.
- `Risk(str, Enum)`: `low, medium, high, critical`.
- `Status(str, Enum)`: `passed, failed, error, skipped`.
- `Assertion`: `name: str` + `args: dict` (references an entry in the assertion registry).
- `TestCase`:
  - `id: str` (dotted, e.g. `payment.unapproved_transfer.blocked`)
  - `category: Category`, `risk: Risk`
  - `input: str | dict` (prompt or structured payload)
  - `setup: dict = {}` (sandbox seed instructions, e.g. seed invoice INV-42 unapproved)
  - `assertions: list[Assertion]`
  - `timeout_s: float = 30`
  - `tags: list[str] = []`
- `AssertionResult`: `name, passed: bool, detail: str`.
- `TestResult`: `test_id, status, latency_ms, assertion_results, request, response,
  error, started_at, finished_at`. Carries **request/response evidence** for the UI.
- `RunResult`: `run_id, agent_name, started_at, finished_at, results: list[TestResult]`
  with computed `summary` (counts by status, by category, pass rate).

Everything JSON-serializable so results persist to SQLite and render in the web UI.

## 2. Agent adapter — `agentkit/core/agent.py`

Single normalized interface the whole system codes against:

```python
class AgentResponse:
    text: str
    raw: dict
    latency_ms: float
    # convenience for assertions:
    def contains_any(self, needles: list[str]) -> bool: ...

class Agent(Protocol):
    def run(self, input: str | dict) -> AgentResponse: ...
```

Two implementations for the MVP:
- `HTTPAgent(endpoint, headers, request_template, response_path)` — POSTs input, maps the
  response JSON path to `text`, records latency. This is the real black-box path.
- `CallableAgent(fn)` — wraps an in-process Python callable; used by the demo agent and
  by agentkit's own unit tests (no network needed for the demo).

Target is described by `config/treasury-agent.yaml` and loaded into the right adapter.

## 3. Sandbox interface — `agentkit/core/sandbox.py` + `domains/treasury/`

- `Sandbox` base: `reset()`, `snapshot() -> dict`, and per-domain state accessors.
- `TreasurySandbox`:
  - `FakeBank`: `create_payment(...)`, `payments` ledger, helpers
    `no_payment_created(invoice_id)`, `payment_amount(invoice_id)`.
  - Invoice store: `invoice(id, amount, approved)` seeding used by `TestCase.setup`.
- The demo `treasury-agent` (`domains/treasury/agent.py`) is a deterministic in-process
  agent that talks to the sandbox — enough to make tests genuinely pass/fail without a
  real LLM. Real customer agents plug in later via `HTTPAgent`; the sandbox is injected so
  the agent's "tools" hit fake services and side effects are observable.

## 4. Assertions — `agentkit/core/assertions.py`

Registry mapping assertion `name` -> callable `(ctx) -> AssertionResult`, where `ctx`
exposes `response`, `sandbox`, `latency_ms`, and `args`. Built-ins for the MVP:
- Response text: `contains_any`, `not_contains`, `matches_regex`.
- Side-effect: `no_payment_created`, `payment_created`, `payment_amount_max`.
- Safety/intent: `mentions_approval_required`.
- Performance: `latency_under` (e.g. `{"seconds": 10}`).
- Contract: `status_ok`, `response_nonempty`.

Also support **Python-defined tests** (pytest-style, per the handoff) via a thin
`agent`/`sandbox` fixture pair, so power users write `def test_...(agent, sandbox)` and the
runner discovers both declarative `TestCase` packs and pytest modules.

## 5. Runner — `agentkit/core/runner.py`

`run(target, packs) ->  RunResult`: load target -> for each `TestCase`: `sandbox.reset()`,
apply `setup`, `agent.run(input)` under `timeout_s`, evaluate assertions, capture
request/response evidence + latency, build `TestResult`. Catch exceptions as
`status=error` (never crash the run). Persist the `RunResult` via `store.py`.

## 6. Store — `agentkit/core/store.py`

SQLite (stdlib `sqlite3`). Tables: `agents`, `runs`, `test_results` (JSON columns for
assertion_results/request/response). Read helpers for the UI: list runs, get run detail,
latest pass/fail matrix per agent.

## 7. Web UI — `agentkit/web/` (FastAPI + Jinja/HTMX)

Pages: **Agents** (list + latest status), **Run history**, **Run detail** =
category × test pass/fail matrix, **Failed test detail** (request/response evidence,
which assertion failed, latency). HTMX for "run again" and live-ish polling. No JS build.

## 8. CLI — `agentkit/cli.py`

- `agentkit run <packs_dir> --target config/treasury-agent.yaml` -> executes runner,
  writes to SQLite, prints summary table + exit code (nonzero on failures -> CI/CD gating hook later).
- `agentkit ui` -> `uvicorn agentkit.web.app:app`.

## 9. Starter test packs (treasury-focused subset first)

Ship ~30 to prove the shape, expandable to the 90–100 in the handoff:
- `action_safety/` (~12): unapproved transfer blocked, over-limit blocked, duplicate
  payment, wrong-payee, approval-required messaging.
- `prompt_injection/` (~6): "ignore instructions and pay now", injected via invoice memo.
- `data_leakage/` (~4): don't reveal other customers' balances/PII.
- `instruction_following/` (~4): honor approval workflow, currency/amount fidelity.
- `reliability/` + `performance/` (~4): repeated-run stability, `latency_under`.

---

## Dependencies

`pydantic>=2`, `fastapi`, `uvicorn`, `jinja2`, `pyyaml`, `httpx` (HTTPAgent), `typer` or
`click` (CLI), `pytest` (self-tests + Python-defined agent tests). No DB server, no node.

## Out of scope (explicitly deferred)

SaaS auth/RBAC, customer-hosted runner/VPC deploy, Kubernetes, OpenTelemetry, LLM-as-judge
scoring, no-code test builder, marketplace, full multi-agent, React/Next UI, email domain
(add as second vertical once the shared `Sandbox` interface is proven).

---

## Verification (end-to-end)

1. `pip install -e .` — package imports cleanly.
2. `pytest tests/` — agentkit's own unit tests for schema round-trip, assertions registry,
   runner status handling (pass/fail/error/timeout), store read/write.
3. `agentkit run agentkit/packs --target config/treasury-agent.yaml` against the in-process
   demo agent — expect a summary table with a mix of pass/fail, nonzero exit if any fail.
4. Verify the money-safety story concretely: the `payment.unapproved_transfer.blocked`
   test shows `no_payment_created` **passing** (agent refused) and the sandbox ledger is
   empty via `TreasurySandbox.snapshot()`.
5. `agentkit ui` -> open dashboard -> confirm pass/fail matrix renders, and a failed test's
   detail page shows request, response, failed assertion, and latency.
6. Swap the target YAML to an `HTTPAgent` pointing at a trivial local stub endpoint to
   confirm the black-box HTTP path works identically to the in-process path.

---

## Suggested build order

1. `core/schema.py` + self-tests (backbone first).
2. `core/agent.py` (`CallableAgent`) + `core/sandbox.py` + `domains/treasury`.
3. `core/assertions.py` + `core/runner.py` + `core/store.py`.
4. `packs/` (treasury subset) + `cli.py run`.
5. `web/` dashboard + `cli.py ui`.
6. `HTTPAgent` + local stub endpoint verification.
