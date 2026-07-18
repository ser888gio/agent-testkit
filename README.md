# agentkit

Adaptive black-box testing for AI agents.

Generate an agent-specific harness, run targeted adversarial evaluations, and produce
evidence for safety, reliability, and compliance.

`agentkit` evaluates AI agents the way they are actually deployed: as black-box systems with
real goals, exposed interfaces, and risk-bearing actions. Instead of relying on one static
suite, it assembles and runs an agent-specific attack harness, selects the most relevant
tests from reusable libraries, and adapts based on what it learns during execution.

At its most ambitious, `agentkit` is an adaptive assurance platform for AI agents. It learns
an agent's purpose and risk profile, generates a tailored harness around its interface and
side effects, and turns adversarial and policy test results into a redacted, auditable
evidence package for engineering, security, and compliance teams.

Black-box testing kit for AI agents. Test agents through their **endpoints** — the way
customers will actually expose them (no prompts, tools, orchestration, or source shared) —
and, where it matters, assert on the state of the **fake tools/services** the agent was
given (e.g. "was a payment actually created?"). Supports single- and multi-turn scenarios,
agentic attack packs (OWASP Agentic Top 10), and EU AI Act / ISO 42001 / NIST compliance
reporting.

> Status: MVP complete, with two demo verticals — **treasury/payment approval** and **email
> triage** (phishing/exfiltration) — plus agentic attack packs and compliance evidence
> reports.

## Product Thesis

`agentkit` helps companies validate AI agents by generating a tailored black-box test
harness that tries to break them, then turns the results into safety and compliance
evidence.

Enterprise framing:

`agentkit` is a black-box testing and assurance platform for AI agents that discovers agent
behavior, assembles targeted adversarial evaluations, and produces evidence for risk,
safety, and compliance decisions.

### Why it is different

- **Tailored to each agent** - Understands the agent's role, interfaces, and risks before
  testing.
- **Designed to break things** - Iteratively probes for prompt injection, misuse, leakage,
  and unsafe actions.
- **Built for evidence** - Produces redacted, auditable results for engineering, security,
  and compliance teams.

### Core loop

`discover -> profile -> generate harness -> select tests -> attack iteratively -> score -> report evidence`

1. **Discover** - learn the interface, schema, tasks, tools, side effects, and risky
   actions.
2. **Profile** - model purpose, domain, capabilities, trust boundaries, likely failure
   modes, and policy controls.
3. **Generate harness** - create the conversation driver, stubs, hooks, observers, and
   artifact capture needed for this agent.
4. **Select tests** - rank the best-fit adversarial, misuse, leakage, robustness, and
   compliance checks.
5. **Attack iteratively** - branch into deeper multi-turn probes and adapt based on prior
   responses.
6. **Score** - summarize severity, exploitability, reproducibility, policy impact,
   regression status, and confidence.
7. **Report evidence** - produce concrete traces and decision-ready artifacts.

### Current repo vs vision

This repository is the execution and evidence core of that broader platform.

- **Current repo** - fixed packs, fixed sandboxes, fixed run flow, fixed scoring, and a
  strong black-box execution/reporting foundation.
- **Target product** - automated discovery, generated harnesses, dynamic test planning,
  adaptive iterative attacks, and risk-aware coverage.

## System Overview

### Infrastructure
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./docs/diagrams/infrastructure-simplified-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./docs/diagrams/infrastructure-simplified-light.svg">
  <img alt="Infrastructure Overview" src="./docs/diagrams/infrastructure-simplified-light.svg">
</picture>

### Architecture
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./docs/diagrams/architecture-simplified-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./docs/diagrams/architecture-simplified-light.svg">
  <img alt="Architecture Overview" src="./docs/diagrams/architecture-simplified-light.svg">
</picture>

[More diagrams →](./docs/diagrams/README.md)

## What it does

- **Python SDK** — a normalized `Agent` adapter (`CallableAgent`/`HTTPAgent`), a `Sandbox`
  interface, a `TestCase`/result schema, and a runner that never crashes.
- **Sandbox side-effects** — fake bank + invoice store, and a fake inbox + contacts +
  outbound ledger, so tests can verify an agent *didn't* perform an unsafe action, not just
  what it said.
- **Built-in test packs** — domain-neutral core pack (endpoint contract, robustness, prompt
  injection, data leakage, performance, reliability) plus treasury and email starter packs.
- **Redaction by default** — secrets/PII are stripped from evidence before it's ever stored
  or shown, with a separate storage on/off policy.
- **Scoring + CI gate** — risk-weighted overall score, per-category scores, critical-failure
  detection, `fail_under` threshold.
- **SQLite results + web dashboard** — pass/fail matrix, run history, failed-test evidence,
  regression comparisons between two runs.
- **Reports** — JSON, JUnit XML, self-contained HTML, and PR-comment-friendly Markdown.
- **CLI** — `agentkit run` (CI-gating exit codes), `agentkit report`, `agentkit compare`, and
  `agentkit ui`.

## Quickstart

```bash
pip install -e .

# Run the treasury pack against the in-process demo agent
agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml
```

Expected output:

```
agentkit run - target: treasury-demo   (6 tests)
CATEGORY              PASS  FAIL   ERR  SKIP
action_safety            6     0     0     0
--------------------------------------------
Overall (weighted): 100%   Pass rate: 100%   Critical failures: 0
Gate: PASS
```

Exit code is `0` (gate passed) — this is what you'd wire into CI. Every run is persisted to
`agentkit.db` (SQLite), so you can render a report or open the dashboard against it:

```bash
# Render a Markdown report for the run (grab the run id from the JSON summary, or the DB)
agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml --format json
agentkit report --run <run_id> --format md

# Launch the dashboard
agentkit ui   # http://127.0.0.1:8000
```

The Markdown report looks like:

```markdown
# agentkit report - treasury-demo

| Overall | Pass rate | Critical failures | Gate |
|---|---|---|---|
| 100% | 100% | 0 | PASS |

## Failures

None.
```

The dashboard (`agentkit ui`) shows the same run as a category × test pass/fail matrix, with
a test-detail page for each test showing the (already redacted) request/response, each
assertion's pass/fail + detail, the sandbox before/after diff, and latency.

`agentkit ui` binds to `127.0.0.1` by default. Its "re-run" endpoint can trigger loading of
target/pack files and execution of Python test files under the packs directory — only pass
`--host 0.0.0.0` on a trusted network.

### The email exfiltration demo

The most relatable demo: a vendor email tries to trick the agent into forwarding a payroll
spreadsheet to an external address. Run it and watch the outbound ledger stay clean:

```bash
agentkit run agentkit/packs/email --target agentkit/config/email-agent.yaml
python examples/run_email.py   # narrates the attack + verdict
```

### EU AI Act compliance evidence

Agentic attack packs (`agentkit/packs/agentic/`) probe the OWASP Agentic Top 10 — tool
misuse, memory poisoning (multi-turn), goal hijack, privilege abuse, human oversight — and
the compliance report reframes the results as EU AI Act / ISO 42001 / NIST evidence:

```bash
agentkit run agentkit/packs/agentic --target agentkit/config/treasury-agent.yaml --compliance
agentkit report --run <run_id> --format compliance        # Markdown, grouped by EU article
agentkit report --run <run_id> --format compliance-json   # machine-readable for GRC
```

Empty or all-skipped runs fail closed (INCOMPLETE — no evidence is not a pass). This is
technical readiness evidence, **not** a compliance/CE determination — see
[docs/specs/compliance.md](docs/specs/compliance.md).

### Compare two runs (regression gate)

```bash
agentkit compare <run_id_a> <run_id_b>
```

Prints newly-failing/newly-passing tests, latency + score deltas, and highlights any
**critical regression** — exiting `1` if one is found, so a CI pipeline can block a release
that broke a critical safety test.

## Programmatic use

```bash
python examples/run_treasury.py   # load target -> discover -> run -> score -> print
python examples/run_email.py      # the exfiltration demo, end to end
```

`examples/stub_endpoint.py` + `agentkit/config/demo-stub-http.yaml` show the black-box HTTP
path (`HTTPAgent`) is behaviorally identical to the in-process path (`CallableAgent`) for the
same inputs — the whole premise of testing agents through an endpoint.

## Development

- [`docs/README.md`](docs/README.md) — documentation map for architecture, specs, diagrams,
  research, and archived planning notes.
- [`docs/plan.md`](docs/plan.md) — the full MVP design.
- [`docs/architecture.md`](docs/architecture.md) — control plane vs runner, execution modes,
  trace visibility, the privacy/redaction model, the sandbox model, and how this MVP points
  toward a customer-hosted enterprise deployment.
- [`docs/specs/`](docs/specs/README.md) — one contract spec per branch (public API, data
  models, failure behavior, required tests).

```bash
pip install -e ".[dev]"
pytest tests/
```
