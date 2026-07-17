# Architecture Overview (Simplified)

## System Summary
agentkit is a black-box testing kit for AI agents: it drives a target agent through declarative YAML test packs, checks the effects against fake sandboxes, and scores/reports the results. Used by developers and CI to gate agent behavior, and by anyone reviewing results via a local dashboard.

## Major Components

### Test Packs (YAML/Python)
**Purpose**: Declare what to test — inputs, multi-turn conversations, and pass/fail assertions.
**Contains**: Core, treasury, email, and agentic (OWASP ASI attack) packs; declarative YAML test cases plus a few Python test functions.

### Test Runner Pipeline (Core)
**Purpose**: Load, execute, and score tests against a target agent.
**Contains**: config loader, test discovery, execution/runner (with multi-turn and timeout handling), assertion engine, evidence redaction, and risk-weighted scoring/regression comparison.

### Agent Adapters (HTTP/in-process)
**Purpose**: Talk to the "agent under test" through one common interface.
**Contains**: `HTTPAgent` (httpx calls to an external endpoint) and `CallableAgent` (in-process Python function), both behind a single `Agent` protocol.

### Sandboxes (Fake Bank/Inbox)
**Purpose**: Simulate side effects so assertions can check what the agent actually did, without touching real systems.
**Contains**: Fake treasury/bank sandbox and fake email/inbox sandbox, registered via a pluggable sandbox registry.

### Store (SQLite)
**Purpose**: Persist every run so it can be reported on or compared later.
**Contains**: Agents, runs, and test-result tables in a single local `agentkit.db` file.

### Reports (JSON/JUnit/HTML/MD/Compliance)
**Purpose**: Turn a scored run into a human- or machine-consumable artifact.
**Contains**: JSON, JUnit (CI), HTML, Markdown renderers, plus an EU AI Act / ISO 42001 / NIST / OWASP compliance report.

### CLI (Typer)
**Purpose**: Primary entry point for running tests, generating reports, comparing runs, and launching the dashboard.
**Contains**: `run`, `report`, `compare`, `ui` commands; wires the pipeline together, gates CI on exit code.

### Dashboard (FastAPI)
**Purpose**: Browse persisted runs and results in a browser.
**Contains**: Read-mostly, server-rendered views (Jinja2) over the Store, plus a token-protected route to re-trigger a run.

## Data Flow
1. A test pack (YAML/Python) declares the inputs and assertions.
2. The Runner Pipeline loads the pack and target config, builds a Sandbox and an Agent Adapter.
3. The Agent Adapter sends input to the target agent (HTTP or in-process).
4. The Sandbox records side effects (payments, emails, etc.) before/after each turn.
5. Assertions check the agent's response and sandbox side effects; results are redacted.
6. Scoring produces a risk-weighted score and CI gate decision.
7. Results are persisted to the Store (SQLite).
8. Reports are generated from stored/fresh results, or viewed live in the Dashboard.

## Key Interactions
| From | To | What |
|------|-----|------|
| CLI | Test Runner Pipeline | Triggers a run: load config, discover tests, execute, score |
| Test Runner Pipeline | Agent Adapters | Sends test input, receives agent response |
| Test Runner Pipeline | Sandboxes | Resets/snapshots/diffs fake side effects per test |
| Test Runner Pipeline | Store | Saves redacted run/test results |
| CLI / Dashboard | Reports | Renders a stored or fresh run into JSON/JUnit/HTML/MD/Compliance |
| Dashboard | Store | Reads runs/agents/results for display |
| Dashboard | Test Runner Pipeline | Token-gated re-run of a pack against a target |
