# agentkit — Architecture

This document covers the target architecture for agentkit as a product, using the current
MVP (this repo) as the reference implementation of its core ideas. See [`plan.md`](plan.md)
for the MVP build plan and [`archive/plans/`](./archive/plans) for historical planning
context.

## Control plane vs runner

agentkit splits cleanly into two halves that will eventually run in different trust domains:

- **Control plane** (SaaS): the test library/packs, the scoring engine, the SQLite/Postgres
  result store, the web dashboard, reports, and CI integrations. It never needs direct
  network access to a customer's private agent — it only needs *results*.
- **Runner** (customer-adjacent): the piece that actually calls the agent under test —
  `Agent` (`CallableAgent`/`HTTPAgent`), the `Sandbox` the agent is wired to, and the
  `Redactor` that scrubs evidence before it ever leaves the runner's process.

In this MVP both halves live in one process (`agentkit run` does discovery, execution,
scoring, and persistence in a single call). That collapse is intentional for a fast local
loop, but the module boundary already matches the eventual split: `agentkit/core/runner.py`,
`agentkit/core/agent.py`, and `agentkit/core/sandbox.py` are the "runner" pieces;
`agentkit/core/scoring.py`, `agentkit/core/store.py`, `agentkit/reports/`, and
`agentkit/web/` are the "control plane" pieces. Nothing in the control-plane modules imports
`httpx`, calls an agent, or touches unredacted evidence — they only ever consume
`RunResult`/`ScoreReport` that the runner already produced.

## Execution modes

Three ways a customer can point agentkit at their agent, ordered by how much trust they
extend:

1. **Endpoint-only** — the customer exposes a single HTTP endpoint
   (`POST /run {"input": ...} -> {"text": ...}`). agentkit's `HTTPAgent` calls it exactly
   like any other API consumer would. No prompts, tools, orchestration, or source are ever
   shared. This is the mode `docs/specs/http-verify.md` proves is behaviorally identical to
   the in-process path.
2. **Managed sandbox** — agentkit also owns the fake tools/services (`FakeBank`,
   `FakeInbox`, ...) that the customer's agent is wired to *for the test run only*, so
   action-safety assertions (`no_payment_created`, `no_external_forward`, ...) can observe
   side effects, not just text. This is what `TreasurySandbox`/`EmailSandbox` demonstrate
   today.
3. **Customer-hosted runner (VPC/on-prem)** — for customers who won't let *any* traffic
   leave their network, the runner (agent adapter + sandbox + redactor) deploys inside their
   VPC and only ships already-redacted `RunResult`/`ScoreReport` JSON back to the SaaS
   control plane. The control plane never sees a raw prompt, tool call, or secret. This is
   the direction the module split above is already built for — the runner has zero
   dependency on the control-plane modules.

## Trace visibility

How much of the agent's internals a test run can see, from least to most invasive:

- **Black-box**: request, response, latency, HTTP status. What `HTTPAgent` sees today. Works
  against *any* agent with zero integration effort.
- **Semi-visible**: black-box plus tool/action *events* — the agent (or its harness) reports
  "I called `create_payment`" without exposing the full trace. `Sandbox.record_event` is the
  seam for this: a real customer agent could call `sandbox.record_event(...)` from inside its
  own tool-calling code, same as the demo agents do.
- **Instrumented**: full visibility into LLM calls, tool calls, memory, prompts, agent
  handoffs, and cost — think OpenTelemetry-style tracing. Out of scope for this MVP
  (see `docs/plan.md` "Out of scope"), but the `Event`/`Sandbox.diff` shapes are designed to
  extend into richer trace objects without breaking the `TestResult.sandbox_diff` contract.

**This MVP operates in black-box + sandbox side-effects mode**: agentkit asserts on what the
agent *said* (`AgentResponse.text`) and what it *did* to the fake tools it was given
(`Sandbox.diff`/`Sandbox.events`), never on its internal reasoning.

## Privacy model

- **Redaction is not optional.** `agentkit/core/redaction.py`'s `Redactor` strips API keys,
  bearer tokens, emails, IBANs, card numbers, account numbers, and phone numbers from any
  string/dict/list before it's treated as evidence — see `docs/specs/redaction.md`.
- **`EvidencePolicy`** (`store_request`/`store_response`) is a second, independent control:
  even *redacted* evidence can be dropped entirely (`None`) per target. The runner
  (`agentkit/core/runner.py`) applies both the redaction and the storage policy on every
  `TestResult`; `Store.save_run` re-applies the `Redactor` as a defense-in-depth pass before
  writing to SQLite (`docs/specs/store.md`).
- **No secrets in config files.** `TargetConfig` YAML/JSON interpolates `${ENV_VAR}` at load
  time (`docs/specs/config.md`), so an API token for a customer's endpoint never sits in a
  committed file.
- **Why internals never leave the customer boundary**: in the endpoint-only and
  customer-hosted-runner modes, the *only* thing that crosses into agentkit's control plane
  is a `TestResult` that has already been through the `Redactor` and the `EvidencePolicy`
  filter. The customer's prompts, tool implementations, and orchestration code are never
  transmitted, inspected, or stored — agentkit only ever sees what its own black-box request
  produced.

## Sandbox model

`agentkit/core/sandbox.py`'s `Sandbox` ABC is deliberately domain-agnostic:

- `reset()` / `apply_setup(dict)` — deterministic zero-state per test, seeded from
  `TestCase.setup`.
- `snapshot() -> dict` — a JSON-serializable state dump.
- `diff(before, after) -> dict` — `{"added", "removed", "changed"}`, used both for
  `TestResult.sandbox_diff` (shown in the UI's test detail page) and for regression tooling.
- `events` / `record_event(kind, data)` — an append-only side-effect log the demo agents call
  whenever they take an action; this is what a "semi-visible" trace mode reads.
- `SANDBOXES` registry + `register_sandbox`/`build_sandbox` — new verticals (payroll, CRM,
  ticketing, ...) register a new `Sandbox` subclass without touching `core/`.

`TreasurySandbox` (`FakeBank` + invoice store) and `EmailSandbox` (`FakeInbox` + contacts +
outbound ledger) are the two shipped domain fakes; both plug into the same generic interface,
which is the proof that a third vertical is "write a `Sandbox` subclass," not "rearchitect
the runner."

## Future enterprise deployment

For a company that will not expose their agent's prompts, tools, or source — but wants
agentkit's test packs, scoring, and CI gate — the target deployment looks like:

```
┌─────────────────────────────┐        ┌───────────────────────────────────┐
│   Customer VPC / on-prem    │        │        agentkit SaaS               │
│                              │        │                                     │
│  private agent  <──┐        │        │  test library / packs              │
│                     │        │        │  scoring + regressions             │
│  agentkit runner ───┘        │  JSON  │  result store (Postgres)           │
│   - HTTPAgent/CallableAgent  │───────▶│  web dashboard                     │
│   - Sandbox + fakes          │  redacted, evidence-policy-filtered         │
│   - Redactor                 │  RunResult + ScoreReport only               │
└─────────────────────────────┘        └───────────────────────────────────┘
```

The customer runs the (open-source or licensed) runner inside their own network boundary.
It pulls test packs from the SaaS control plane, executes them against the private agent
exactly as `agentkit run` does today, and pushes back only `RunResult`/`ScoreReport` —
already redacted, already evidence-policy-filtered. The SaaS side never needs inbound
network access to the customer's environment and never receives a raw prompt or tool
implementation. This is a deployment topology change, not a code change: every module this
MVP built (`schema`, `redaction`, `config`, `agent`, `sandbox`, `assertions`, `loader`,
`runner`, `scoring`, `store`) already assumes the runner and the control plane are separable.
