# Infrastructure Documentation

## Overview

agentkit has no infrastructure-as-code: it is a pure-Python local toolkit (Python >= 3.10, `pyproject.toml:10`) whose "infrastructure" is its runtime topology — a Typer CLI process, an optional uvicorn/FastAPI dashboard, an optional external HTTP agent endpoint, in-process fake-service sandboxes, and a SQLite file. Everything runs on one machine by default; the only network traffic is the outbound HTTP call to a target agent and the loopback dashboard.

## Components

### Compute

| Component | Type | Purpose | Configuration | Reference |
|---|---|---|---|---|
| `agentkit` CLI | Local process (Typer) | Entry point: `run`, `report`, `compare`, `ui` subcommands | Console script `agentkit = agentkit.cli:app` | `pyproject.toml:27`, `agentkit/cli.py:25` |
| Test runner | In-process (inside CLI or web process) | Executes tests sequentially against agent + sandbox; never raises | Per-test timeout via a single-worker `ThreadPoolExecutor` (`_run_with_timeout`) | `agentkit/core/runner.py:30-41,224-250` |
| Dashboard server | uvicorn + FastAPI process | Serves web UI over the Store | Default `127.0.0.1:8000`; overridable `--host/--port`; started via `uvicorn.run("agentkit.web.app:app", ...)` | `agentkit/cli.py:194-209` |
| CallableAgent | In-process adapter | Imports a Python factory (`module:attr`), calls it directly; passes sandbox if the callable accepts a `sandbox` kwarg | `type: callable` in target YAML | `agentkit/core/agent.py:39-70,159-166` |
| HTTPAgent | Network client (httpx, sync) | Calls an external agent endpoint per test turn | `type: http` spec: endpoint, method (POST/GET), headers, request template, `text_path` response extraction, `timeout_s` (default 30) | `agentkit/core/agent.py:100-156`, `agentkit/core/config.py:34-41` |
| Sandboxes (treasury, email) | In-process objects, NOT networked | Fake bank/invoices and inbox/outbound-ledger; record side-effect events, snapshot/diff state | Registered via `@register_sandbox` into `SANDBOXES` registry; built per run | `agentkit/core/sandbox.py:71-91`, `agentkit/domains/treasury/sandbox.py:33-58`, `agentkit/domains/email/sandbox.py` |
| Example stub endpoint | Separate uvicorn process (optional, demo) | Hosts the demo agent over HTTP: `POST /run {"input"} -> {"text"}` | `uvicorn examples.stub_endpoint:app --port 8001` | `examples/stub_endpoint.py:1-27` |

### Data Stores

| Component | Type | Purpose | Configuration | Reference |
|---|---|---|---|---|
| `agentkit.db` | SQLite file (stdlib `sqlite3`) | Persists agents, runs, test_results (redacted evidence JSON) | Path via `--db` (CLI, default `agentkit.db`) or `AGENTKIT_DB` env (web); gitignored, safe to delete | `agentkit/core/store.py:15-43,77-82`, `agentkit/web/app.py:72-73` |
| YAML test packs | Read-only files | Test cases in `agentkit/packs/{core,treasury,email,agentic}/` (27 YAML files) plus Python tests (`packs/core/_demo_safe_agent.py`) | Discovered from a packs dir argument | `agentkit/core/loader.py`, `agentkit/cli.py:91` |
| Target configs | YAML/JSON files | Agent endpoint/callable, sandbox choice, evidence policy | `agentkit/config/*.yaml`; `${VAR}` env interpolation | `agentkit/core/config.py:54-109` |
| Report artifacts | Generated files/stdout | json, junit, html, md, compliance, compliance-json renderings | Written only when `--out` given, else stdout | `agentkit/reports/__init__.py:13-28`, `agentkit/cli.py:153-156` |
| Jinja2 templates + static | Package files | Dashboard HTML; `/static` mount | `agentkit/web/templates/`, `agentkit/web/static/` | `agentkit/web/app.py:61-69` |

### Networking

| Endpoint | Direction | Protocol | Notes | Reference |
|---|---|---|---|---|
| `http://127.0.0.1:8000` | Inbound (browser -> dashboard) | HTTP | Routes: `GET /`, `/agents`, `/agents/{id}`, `/runs/{id}`, `/runs/{id}/tests/{id}`, `/runs/{id}/status` (HTML or JSON), `GET /compare`, `POST /runs` (token-gated), `/static` | `agentkit/web/app.py:85-191` |
| Target agent endpoint | Outbound (runner -> agent) | HTTP via httpx, synchronous | From target config, e.g. `http://localhost:8001/run` (`treasury-http.yaml:4`); auth header `Bearer ${AGENT_TOKEN}` interpolated from env (`treasury-http.yaml:7`) | `agentkit/core/agent.py:111-117` |
| `http://localhost:8001/run` | Inbound to demo stub | HTTP | Only when the example stub is run | `examples/stub_endpoint.py:6,20` |

There are no other network calls: no LLM/SDK APIs, no telemetry, no external SaaS anywhere in `agentkit/`. Callable targets and sandboxes are pure in-process.

### Security

| Mechanism | Detail | Reference |
|---|---|---|
| Evidence redaction | `Redactor` masks builtin patterns (api_key, bearer, email, IBAN, card, account, phone) plus config-defined patterns/literals; applied to request, response, assertion detail, sandbox diff, and error text before storage or rendering | `agentkit/core/redaction.py:18-81`, `agentkit/core/runner.py:55-80,129-143`, `agentkit/core/store.py:87-131` |
| Evidence policy | `store_request`/`store_response` toggles per target; off = evidence stored as null | `agentkit/core/redaction.py:40-43` |
| Web access token | `POST /runs` requires token from `AGENTKIT_WEB_TOKEN` env or a per-process `secrets.token_urlsafe(16)`; compared with `secrets.compare_digest` | `agentkit/web/app.py:36,54-59,171` |
| Path allowlisting | Web `POST /runs` resolves `target`/`packs` only under `agentkit/config/` or `agentkit/packs/`, blocking arbitrary callable loading | `agentkit/web/app.py:31-51` |
| Secrets in config | Never stored literally; `${VAR}` placeholders resolved from process env at load time, error if unset | `agentkit/core/config.py:54-70` |

### External Services

| Service | Role | Reference |
|---|---|---|
| Target AI agent (user-provided) | The system under test; any HTTP endpoint matching the request/response template, or any importable Python callable | `agentkit/core/config.py:29-44` |
| None else | No cloud providers, LLM APIs, message queues, or third-party SaaS are referenced in runtime code | verified by env-var and import scan |

## Relationships

| From | To | Mechanism | Data | Sync/Async |
|---|---|---|---|---|
| User shell | CLI process | Typer argv | commands, flags | sync |
| CLI `run` | Loader | file reads | pack YAML / Python tests (`cli.py:91`) | sync |
| CLI `run` / web `POST /runs` | Runner | function call | TargetConfig + tests (`cli.py:103`, `web/app.py:174`) | sync |
| Runner | Sandbox | method calls | reset/apply_setup/snapshot/diff/events (`runner.py:93-112`) | sync, in-process |
| Runner | HTTPAgent | httpx request | rendered request JSON -> response body (`agent.py:111`) | sync (thread-wrapped for timeout, `runner.py:30-41`) |
| Runner | CallableAgent | direct call | input str/dict (+ sandbox ref) -> AgentResponse (`agent.py:48-70`) | sync |
| CallableAgent target | Sandbox | direct object ref | side effects: payments, sent mail (`agent.py:52`) | sync |
| Runner | Redactor | function call | evidence before storage (`runner.py:129-143`) | sync |
| CLI / web | Store | sqlite3 | save_run / get_run / list_runs / matrix (`store.py:87-219`) | sync, file `agentkit.db` |
| Store | Redactor | function call | second redaction pass on save (`store.py:88,122-131`) | sync |
| CLI `report` | Renderers | function call | RunResult+ScoreReport -> json/junit/html/md/compliance (`reports/__init__.py:23`) | sync |
| CLI `compare` / web `/compare` | regressions.compare | function call | two stored runs -> diff (`cli.py:173`, `web/app.py:185`) | sync |
| Browser | Dashboard | HTTP loopback | HTML (Jinja2), JSON status | sync |
| Dashboard | agentkit.db | via Store, new connection per request (`web/app.py:76-77`) | reads + run inserts | sync |
| CI system | CLI exit code | process exit | 0 pass / 1 gate-fail / 2 config error (`cli.py:88,130,191`) | sync |

## Environment Differences

Single local environment. No dev/staging/prod split exists. Variation points are runtime knobs only: `--db` / `AGENTKIT_DB` (database path), `--host/--port` (dashboard bind), `AGENTKIT_WEB_TOKEN` (dashboard write token), and arbitrary `${VAR}` references in target configs (e.g. `AGENT_TOKEN` in `agentkit/config/treasury-http.yaml:7`).

## Unverified Items

- **Public-bind rejection not implemented**: the comment at `agentkit/web/app.py:34-35` says "Reject public binding unless explicitly overridden", but neither `app.py` nor `cli.py:194-209` contains a host check — `agentkit ui --host 0.0.0.0` binds publicly without complaint. Code wins over comment: treat as aspirational/doc drift.
- **Access token usability**: when `AGENTKIT_WEB_TOKEN` is unset, the generated token (`web/app.py:36`) is never printed or logged anywhere I can find, making `POST /runs` effectively unusable in that mode. UNVERIFIED whether a template or startup path surfaces it (templates not exhaustively read).
- **`demo-stub-http.yaml` endpoint** `http://stub/run` (`agentkit/config/demo-stub-http.yaml:4`) is not a resolvable host; presumed a test fixture target, not a runnable config.
- **Email sandbox internals** documented at the interface level (register/reset/snapshot/events via `agentkit/core/sandbox.py`); `agentkit/domains/email/sandbox.py` was not read line-by-line, but its role (in-process fake inbox/outbound ledger, no network) follows the same registry pattern as treasury.
