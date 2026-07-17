# Infrastructure Overview (Simplified)

## System Summary
agentkit runs entirely on one developer machine — no cloud, no IaC. A CLI drives test runs against a target AI agent, records results in a local SQLite file, and an optional local web dashboard displays them.

## Major Components

### CLI (Typer)
**Purpose**: Entry point for running tests, generating reports, and comparing runs.
**Contains**: `run`, `report`, `compare`, `ui` subcommands; the in-process test runner.

### Dashboard (FastAPI/uvicorn)
**Purpose**: Local web UI for browsing runs and results.
**Contains**: Loopback HTTP server (default `127.0.0.1:8000`), token-gated write endpoint.

### Target Agent Under Test
**Purpose**: The AI agent being evaluated — external to agentkit.
**Contains**: Either an outbound HTTP call (via httpx) to a user-provided endpoint, or a direct in-process Python callable.

### In-Process Sandboxes (Treasury, Email)
**Purpose**: Fake services that simulate side effects (bank/invoices, inbox/outbound mail) so test assertions can check what the agent actually did.
**Contains**: No networking — pure in-memory state, snapshot/diff/event recording.

### Store (SQLite)
**Purpose**: Persists agents, runs, and redacted test evidence to a single local file (`agentkit.db`).

### Config & Test Packs (YAML)
**Purpose**: Declarative test cases and target definitions read from disk at run time.

### Redaction Layer
**Purpose**: Strips secrets/PII (API keys, emails, IBANs, etc.) from evidence before it's stored or rendered.

## Data Flow
1. User invokes CLI `run` (or dashboard `POST /runs`) with a target config and test pack.
2. CLI loads YAML test cases and the target definition.
3. Runner resets a sandbox, then dispatches each test to the target agent (HTTP or in-process callable).
4. Runner captures the agent's response and the sandbox's side-effect diff.
5. Redaction layer scrubs sensitive data from the captured evidence.
6. Results are written to the SQLite store.
7. Dashboard (or `report`/`compare` commands) reads from the store to display or export results.

## Key Boundaries
| Boundary | Inside | Outside |
|----------|--------|---------|
| Local machine | CLI, dashboard, sandboxes, SQLite store, config/test files | Target agent (if HTTP-based) |
| Network | Loopback dashboard traffic | Outbound call to target agent endpoint |
| Trust/redaction | Raw agent request/response before redaction | Anything persisted or rendered (always post-redaction) |
