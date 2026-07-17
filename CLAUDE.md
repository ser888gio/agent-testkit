# agentkit

Black-box testing kit for AI agents: test agents through their endpoints (single- and
multi-turn) and assert on sandbox side-effects (fake bank, inbox, etc.). Includes agentic
attack packs (OWASP Agentic Top 10) and an EU AI Act / ISO 42001 / NIST compliance report.
Python 3.10+, Pydantic v2, FastAPI, Typer.

## Commands

```bash
.venv/Scripts/python -m pytest              # run tests (Windows venv)
agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml
agentkit run agentkit/packs/agentic --target agentkit/config/treasury-agent.yaml --compliance
agentkit ui                                 # dashboard at http://127.0.0.1:8000
agentkit report --run <run_id> --format md  # also: compliance, compliance-json
agentkit compare --base <run_id> --head <run_id>
```

## Layout

- `agentkit/core/` — Agent adapters, Sandbox, TestCase/result schema, runner (multi-turn), scoring, redaction, compliance mapping, regressions, SQLite store
- `agentkit/domains/` — fake services (bank/invoices, inbox/contacts/outbound ledger)
- `agentkit/packs/` — YAML test packs: core (contract, injection, leakage, perf), treasury, email, agentic (tool misuse, memory poisoning, goal hijack, privilege abuse, code execution, human oversight)
- `agentkit/reports/` — JSON / JUnit / HTML / Markdown / compliance renderers
- `agentkit/web/` — FastAPI dashboard (Jinja2 templates)
- `agentkit/cli.py` — Typer CLI entry point
- `tests/` — pytest suite; shared fixtures in `tests/_fixtures.py`
- `examples/` — runnable demos (`demo_agent.py`, `run_treasury.py`, `run_email.py`)
- `docs/` — `architecture.md`, `plan.md`, specs (incl. `specs/compliance.md`) and notes
- `docs/diagrams/` — D2 sources + rendered SVGs (light/dark) used by the README

## Conventions

- Runner never crashes: agent/sandbox errors become test results, not exceptions.
- Redaction happens before evidence is stored or rendered — never log raw request/response.
- Every run persists to `agentkit.db` (gitignored artifact, safe to delete).
- CI gating uses exit codes from `agentkit run` (`fail_under` threshold).
- Compliance reporting fails closed: empty/all-skipped runs are INCOMPLETE, never a pass. It is technical evidence, not a CE/compliance determination.
