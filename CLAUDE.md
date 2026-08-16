# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview

**agentkit** is a black-box testing kit for AI agents. It calls an agent through its endpoint
(in-process callable or HTTP), asserts on both what the agent *said* and what it *did* to the
fake tools it was given, scores the run, persists it, and renders reports — including an
EU AI Act / ISO 42001 / NIST compliance view. Single Python package, Python 3.10+,
Pydantic v2, FastAPI, Typer, managed with `uv`.

One-sentence positioning:

> `agentkit` helps companies validate AI agents by generating a tailored black-box test
> harness that tries to break them, then turns the results into safety and compliance
> evidence.

Enterprise framing:

> `agentkit` is a black-box testing and assurance platform for AI agents that discovers
> agent behavior, assembles targeted adversarial evaluations, and produces evidence for
> risk, safety, and compliance decisions.

### Product direction

The intended product loop is:

`discover -> profile -> generate harness -> select tests -> attack iteratively -> score -> report evidence`

What each stage means:

1. **Discover** - learn endpoint shape, input/output schema, supported tasks, visible tools,
   side effects, and risk-sensitive actions.
2. **Profile** - model the agent's purpose, domain, capabilities, trust boundaries, likely
   failure modes, and applicable policy controls.
3. **Generate harness** - assemble a conversation driver, environment stubs, validation
   hooks, side-effect observers, artifact capture, and retry/escalation logic.
4. **Select tests** - rank the most relevant robustness, prompt injection, leakage, misuse,
   domain-specific, and compliance checks.
5. **Attack iteratively** - branch into deeper multi-turn probes, mutate attacks based on
   prior responses, and stop when coverage or confidence thresholds are reached.
6. **Score** - summarize severity, exploitability, reproducibility, policy impact,
   regression status, and confidence.
7. **Report evidence** - emit artifacts for engineering, security, governance, and release
   decisions.

The differentiator is not just "we have tests." It is "we know which tests matter for this
agent, and how to push farther when it starts to crack."

### Current repo vs target product

Keep the story honest when describing this codebase:

- **Current repo** - fixed packs and sandboxes, solid black-box execution, solid
  evidence/reporting foundations, plus a first adaptive layer: endpoint probing into an
  `AgentProfile`, a metadata catalog with explainable ranking, a planner that records why
  each test was selected and what was left untested, and adapters normalizing promptfoo and
  garak reports. Adapter-selected tests are ranked and their invocation generated, but they
  are still executed out of band.
- **Target product** - automated agent discovery, generated harnesses, dynamic test
  planning, adaptive iterative attacks, risk-aware coverage, and a stronger assurance
  narrative.

The practical framing for contributors is:

> This repo is the execution and evidence core of a larger adaptive agent assurance
> platform.

Suggested next product milestones (1-3 and 5 shipped; see
[`IMPLEMENTATION-TESTS-PLAN.md`](IMPLEMENTATION-TESTS-PLAN.md) for the full roadmap):

1. ~~`AgentProfile` model.~~ — `core/profile.py`, `core/discovery.py`
2. ~~Test-library metadata tagged by domain, capability, risk, and preconditions.~~ — `core/catalog.py`
3. ~~Planner that ranks tests from profile plus risk.~~ — `core/planner.py`
4. Iterative attack loop with branching and retries.
5. ~~Reporting that explains why a test was selected for a given agent.~~ — `reports/plan.py`
6. Adapter *execution*: today `core/adapters.py` normalizes promptfoo/garak reports and
   generates their config/argv, but agentkit does not spawn either tool.

**Non-obvious structural fact:** the `agentkit` package is physically split across four
top-level directories and reassembled by an explicit setuptools package map
(`pyproject.toml` → `[tool.setuptools] packages = [...]` + `[tool.setuptools.package-dir]`,
one entry per subpackage). This replaced the earlier implicit namespace-package discovery
(`[tool.setuptools.packages.find] where = [".", "backend", "frontend"]`) so that
`infra/alembic/` (migrations) ships inside the installed wheel as `agentkit.migrations` /
`agentkit.migrations.versions` — namespace-package `find` had no way to reach outside
`where`. At import time there is exactly one `agentkit` package. `agentkit.core` lives under
`backend/` (including `agentkit.cli`), `agentkit.web` under `frontend/`,
`agentkit.packs`/`agentkit.config` at the root, and `agentkit.migrations` under
`infra/alembic/`. Import paths never mention `backend`/`frontend`/`infra`.

Where things live:

- **Business logic / test engine** — `backend/agentkit/core/` (runner, assertions, scoring, loader)
- **Domain fakes (sandboxes)** — `backend/agentkit/domains/` (treasury: bank+invoices; email: inbox+contacts+outbound ledger)
- **Persistence** — `backend/agentkit/core/store.py` (SQLite, `agentkit.db`)
- **HTTP surface** — `frontend/agentkit/web/app.py` (FastAPI dashboard + Jinja2 templates)
- **CLI** — `backend/agentkit/cli.py` (Typer; the `agentkit` console script)
- **Test content (data, not code)** — `agentkit/packs/**/*.yaml`
- **Repo tests** — `tests/` (pytest, one file per module)
- **Infrastructure** — `infra/` (Dockerfile, compose, `dev.sh`, `infra/alembic/` migrations)
- **DB schema migrations** — `infra/alembic/` (Alembic, raw SQL via `op.execute`, no ORM
  models); driven by the `agentkit migrate` CLI subcommand, config in root `alembic.ini`

Generated / vendored — **never edit by hand:** `dist/`, `agentkit.egg-info/`, `.venv/`,
`agentkit.db`, `**/__pycache__/`, `uv.lock` (regenerate via `uv lock`),
`docs/diagrams/*.svg` (rendered from the `.d2` sources beside them).

## Repository map

```text
agentkit/              config/*.yaml (targets) · packs/ (YAML test packs)
backend/agentkit/
  cli.py               Typer CLI (the `agentkit` console script)
  core/                agent · sandbox · schema · loader · runner · assertions
                       scoring · redaction · compliance · regressions · store
                       profile · discovery · catalog · planner · adapters
  domains/             treasury/ · email/  (Sandbox subclasses + demo agents)
  reports/             json · junit · html · md · compliance · plan renderers
frontend/agentkit/web/ app.py · templates/ · static/
tests/                 pytest suite · _fixtures.py
docs/                  architecture.md · plan.md · specs/ · diagrams/ · components.yaml
tools/                 validate.sh · affected.sh · guard-protected-paths.sh
infra/                 Dockerfile · docker-compose.yml · dev.sh · alembic/ (DB migrations)
```

Machine-readable component map with dependencies and validation commands:
[`docs/components.yaml`](docs/components.yaml). Update it when component boundaries change.

## Standard commands

All commands below were executed successfully in this repository.

| Purpose | Command |
| --- | --- |
| Install deps | `uv sync --extra dev` |
| Editable install | `pip install -e .` |
| Unit tests (full suite, 493 tests, ~150s) | `python -m pytest` |
| Single test file | `python -m pytest tests/test_runner.py` |
| Single test | `python -m pytest tests/test_runner.py -k name` |
| Lint | `python -m ruff check .` |
| Format | `python -m ruff format .` |
| Build dists | `uv build` |
| Apply DB migrations | `agentkit migrate --db <path>` |
| Migration status | `agentkit migrate --db <path> --status` |
| Dev dashboard | `bash infra/dev.sh` (serves `127.0.0.1:8000`) |
| Affected scope | `bash tools/affected.sh` |
| Affected validation | `bash tools/validate.sh --affected` |
| Full validation | `bash tools/validate.sh` |

**Known environment issues — read before picking a command:**

- **On Windows, call pytest as a module, not as a console script.** `uv run --frozen --extra
  dev pytest` fails with `uv trampoline failed to canonicalize script path`; the equivalent
  `uv run --frozen --extra dev python -m pytest` runs the full suite green. This is a
  console-script trampoline issue, not the multi-root package layout — `uv run` itself works
  fine here, and `uv run ... ruff` works as a script too. CI (Linux) runs the console-script
  form and passes.
- **`tools/validate.sh` probes for a runner that has both pytest and ruff**, so prefer it
  over calling the tools directly.
- **Repo-wide lint is green and enforced.** `python -m ruff check .` passes, and CI has a
  `lint` job wired into the `required` gate, so a new violation fails the build.
  `tools/validate.sh` lints the whole repo (`--lint-all` is now a no-op kept for
  compatibility). Any violation you see is one your change introduced.
- **`agentkit` is configured as a first-party import** (`[tool.ruff.lint.isort]
  known-first-party`). The package lives under `backend/`/`frontend/` rather than beside
  `pyproject.toml`, so without that setting ruff sorts it in with third-party packages and
  quietly reformats import blocks the wrong way.

There is **no type-checker configured** in this repository — do not run or document one.
There is no separate integration/e2e runner either: `tests/test_http_agent.py`,
`tests/test_web.py`, and `tests/test_cli.py` are the integration-level coverage and run
inside the same pytest suite. There is **no `examples/` directory** — it held only stale
`__pycache__` and was removed. The `agentkit run ...` commands below are the maintained,
tested way to exercise the tool by hand; do not reintroduce example scripts without also
wiring them into CI, which is how the previous ones rotted unnoticed.

Product commands (exercising agentkit itself, useful for manual verification):

```bash
agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml
agentkit run agentkit/packs/agentic  --target agentkit/config/treasury-agent.yaml --compliance
agentkit plan agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml
agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml --plan --max-tests 8
agentkit report --run <run_id> --format md      # also: json, junit, html, compliance, compliance-json, plan
agentkit compare <run_id_a> <run_id_b>
agentkit ui
```

## Validation ladder

Work up this ladder; stop when the change is covered. Do not jump straight to the bottom rung.

1. **Closest test** — `python -m pytest tests/test_<module>.py -k <name>`
2. **Affected component tests** — `bash tools/validate.sh --affected`
3. **Lint the affected files** — included in step 2
4. **Contract-level tests when interfaces change** — schema/config/assertion registry changes
   touch nearly everything: run the full suite
5. **User-facing flows** — CLI change → `tests/test_cli.py`; dashboard change →
   `tests/test_web.py` plus a manual `agentkit ui` check
6. **Full validation before completion** — `bash tools/validate.sh`

The full suite is ~150 seconds. Most of that is process spawn: since T16 every `runner.run`
call starts a sandbox supervisor plus a nested agent worker (`core/isolation.py`), costing
~2.5s per run on Windows. Production pays that once per run (and respawns only after a
timeout), but the suite calls `run` dozens of times. Prefer step 2 while iterating and step 6
before declaring done.

## Architecture rules

**Confirmed** (enforced by code structure and verified by inspection):

- **Runner / control-plane split.** Runner modules (`core/agent.py`, `core/sandbox.py`,
  `core/redaction.py`, `core/runner.py`) are the only ones that touch a live agent or
  unredacted evidence. Control-plane modules (`core/scoring.py`, `core/store.py`,
  `core/compliance.py`, `core/regressions.py`, `reports/`) consume only an
  already-redacted `RunResult`/`ScoreReport`. `httpx` is imported in exactly one place —
  `backend/agentkit/core/agent.py`. Keep it that way.
- **Dependency direction:** `cli` / `web` → `core` + `reports` + `domains`;
  `reports` → `core` only; `domains` → `core.sandbox` only. `core` imports nothing from
  `domains`, `reports`, `web`, or `cli`. Never add a reverse edge.
- **Redaction is not optional.** `Redactor` runs in the runner before a `TestResult` is
  built, and `Store.save_run` re-applies it as a defense-in-depth pass. Never log or persist
  a raw request/response. `core/adapters.py` is the one path that does not go through the
  runner — third-party reports are normalized outside it — so `normalize()` redacts and
  applies the `EvidencePolicy` itself. Any future non-runner source of `TestResult`s owes
  the same.
- **The runner never crashes.** Agent and sandbox failures become `TestResult`s with
  `Status.ERROR`, never propagated exceptions. See `core/runner.py`.
- **Compliance fails closed.** Empty or all-skipped runs are `INCOMPLETE`, never a pass.
  It is technical evidence, not a CE/compliance determination.
- **New verticals are additive.** A new domain is a `Sandbox` subclass decorated with
  `@register_sandbox("name")` under `backend/agentkit/domains/`. It requires no change to
  `core/`.
- **Test placement:** repo tests live in `tests/`, one file per module
  (`tests/test_<module>.py`). Product test *content* lives in `agentkit/packs/` as YAML and
  is data, not pytest.
- **Contracts:** the shared schema is `backend/agentkit/core/schema.py`
  (`TestCase`, `TestResult`, `RunResult`, `Category`, `Risk`, `Status`); the target-config
  contract is `core/config.py`; the assertion contract is the `REGISTRY` in
  `core/assertions.py`. Changing any of these is a breaking change across every consumer.
- **Persistence access:** only through `Store` (`core/store.py`). No other module opens
  `agentkit.db` or issues SQL.

**Recommendations** (not enforced, follow unless there is a reason not to):

- Prefer adding a YAML pack over a Python test file when expressing new agent test content.
- Keep `frontend/agentkit/web/app.py` thin — push logic into `core/` where it is testable
  without a TestClient.

Deeper reasoning, trust domains, and the target deployment topology:
[`docs/architecture.md`](docs/architecture.md). Per-module specs: [`docs/specs/`](docs/specs/).

## Claude Code working rules

- Identify the affected components before editing — `bash tools/affected.sh` and
  `docs/components.yaml` are the fastest way.
- Inspect existing tests and a similar existing implementation before writing new code.
  This repo is highly patterned; there is almost always a precedent.
- Use targeted validation while iterating; run `bash tools/validate.sh` before declaring done.
- Do not refactor code unrelated to the task.
- Never edit generated or vendored files directly (see the list above); regenerate instead.
- Cite file paths and symbols (`core/runner.py:run`) when making architectural claims.
- Distinguish confirmed findings from inference. Say which one you are reporting.
- Stop and explain before expanding materially beyond the planned scope.
- Prefer the smallest complete change.

Directory-level `CLAUDE.md` files exist under `backend/agentkit/core/`,
`backend/agentkit/domains/`, `frontend/agentkit/web/`, `agentkit/packs/`, and `tests/`;
they add local rules on top of this file. Path-scoped rules live in `.claude/rules/`,
subagents in `.claude/agents/`, and the explore/plan/implement/review workflows in
`.claude/commands/`.

Contributor guide for this setup: [`docs/claude-code.md`](docs/claude-code.md).
