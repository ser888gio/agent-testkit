# agentaudit

Black-box testing for AI agents: call the agent through its real endpoint, assert on what
it *said* and what it *did* to fake tools/services around it, score the run, and get a
report you can gate CI on.

**Who it's for:** teams shipping an AI agent (support bot, payments assistant, internal
copilot) who need to answer "does it still refuse to do the unsafe thing?" with evidence,
not vibes — before every merge, not just at launch.

**Why it exists:** most agent evaluation tools either grade free-text output or require
instrumenting the agent's internals. agentaudit does neither: it treats the agent as a black
box (no prompts/tools/source shared) and checks the side effects against a fake sandbox —
"the agent said it wouldn't pay the invoice, and the invoice store confirms it didn't."

> Status: MVP. Two working demo verticals (treasury payment approval, email
> phishing/exfiltration), an OWASP Agentic Top 10 attack pack, and an EU AI Act / ISO 42001
> / NIST evidence report. See [Limits](#limits) before you rely on it.

## Test your agent in two minutes

Install, then point it at your agent's URL. `agentaudit/packs/core` is 14 domain-agnostic
tests — prompt injection, data leakage, robustness, reliability, latency, response
contract — that need no sandbox:

```bash
git clone https://github.com/ser888gio/agent-testkit.git
cd agent-testkit
pip install -e .
agentaudit run agentaudit/packs/core --endpoint https://your-agent.example.com/chat
```

```text
agentaudit run - target: your-agent.example.com   (14 tests)
CATEGORY              PASS  FAIL   ERR  SKIP
data_leakage             1     1     0     0
endpoint_contract        3     0     0     0
performance              1     0     0     0
prompt_injection         0     2     0     0
reliability              6     0     0     0
--------------------------------------------
Overall (weighted): 62%   Pass rate: 79%   Critical failures: 0
```

`--endpoint` assumes the common shape: `POST {"input": "..."}` returning `{"text": "..."}`.
Anything else — auth headers, a different request body, a nested reply field — needs a
target config, [below](#when-you-need-auth-headers-or-a-different-request-shape).

Endpoints must be `https` and publicly routable — the egress policy
([`core/egress.py`](backend/agentaudit/core/egress.py)) rejects loopback and private ranges
unless the worker sets `AGENTAUDIT_EGRESS_ALLOW_LOCAL=1`.

**`agentaudit: command not found`?** `pip` put the console script in a directory that is not
on your `PATH` — it says so in a `WARNING:` line near the end of the install output. Either
run the module directly:

```bash
python -m agentaudit.cli run agentaudit/packs/core --endpoint https://your-agent.example.com/chat
```

or add the directory `pip` named to your `PATH` (Windows user installs land in
`%APPDATA%\Python\PythonXY\Scripts`, Linux/macOS in `~/.local/bin`).

The exit code is the CI gate — non-zero when the run fails its threshold or a critical
safety test fails. Every run is persisted to `agentaudit.db` (SQLite):

```bash
agentaudit run agentaudit/packs/core --endpoint https://your-agent.example.com/chat --format json
agentaudit report --run <run_id> --format md   # or: json, junit, html, compliance, plan
agentaudit ui                                   # dashboard at http://127.0.0.1:8000
```

`agentaudit ui` binds to `127.0.0.1` and enables local dev auth by default; a non-loopback
bind requires `AGENTAUDIT_AUTH_MODE=oidc` with full OIDC config. See
[`docs/keycloak.md`](docs/keycloak.md).

### When you need auth headers or a different request shape

Write a target config instead of `--endpoint`:

```bash
cp agentaudit/config/my-agent.example.yaml agentaudit/config/my-agent.yaml
# edit endpoint / request shape / response path, then:
export AGENT_TOKEN=...
agentaudit run agentaudit/packs/core --target agentaudit/config/my-agent.yaml
```

```yaml
id: my-agent
agent:
  type: http
  endpoint: "https://your-agent.example.com/chat"
  method: POST
  headers:
    Authorization: "Bearer ${AGENT_TOKEN}"   # from env, never a literal secret
  request:
    json:
      message: "{{ input }}"                 # {{ input }} = the test prompt
  response:
    text_path: "$.reply"                     # where the reply lives in the JSON
  timeout_s: 30
```

Three knobs do the work: `request` is your request body with `{{ input }}` wherever the
prompt goes, `text_path` is the dotted JSON path to the reply, and `${VAR}` interpolates
env vars at load time so tokens stay out of the file. Anything under `request` that
`httpx` accepts (`json`, `params`, `data`, `content`) is passed through.

### Which pack to run

`packs/core` asserts on what the agent *said*, so it applies to any agent — that's the one
to start with. The domain packs (`packs/treasury`, `packs/email`, `packs/agentic`) assert on
what the agent *did* to fake tools, so they need a matching `sandbox:` in the target config
and only apply to agents in those domains. Testing a payments or email agent means writing a
`Sandbox` subclass for your tools — see
[`backend/agentaudit/domains/`](backend/agentaudit/domains/) for the two worked examples.

## System overview

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

- **Black-box `Agent` adapter** — `CallableAgent` (in-process) or `HTTPAgent` (real
  endpoint), same test suite against either.
- **Sandbox side-effects** — a fake bank + invoice store, and a fake inbox + contacts +
  outbound ledger, so a test can check the agent *didn't* wire the payment or exfiltrate the
  file, not just what it claimed.
- **Test packs as YAML** — a domain-neutral core pack (contract, robustness, prompt
  injection, data leakage, performance, reliability) plus treasury and email packs, plus an
  OWASP Agentic Top 10 pack (tool misuse, memory poisoning, goal hijack, privilege abuse).
- **Redaction by default** — secrets/PII stripped from evidence before it's stored or shown;
  storage on/off is a separate policy.
- **Scoring + CI gate** — risk-weighted score, per-category breakdown, critical-failure
  detection, `fail_under` threshold, non-zero exit on gate failure.
- **Regression gate** — `agentaudit compare <run_a> <run_b>` diffs two runs and exits `1` if a
  previously-passing critical safety test now fails.
- **Reports** — JSON, JUnit XML, self-contained HTML, PR-comment Markdown, and an EU AI Act
  / ISO 42001 / NIST evidence report grouped by regulatory obligation.
- **SQLite store + dashboard** — pass/fail matrix, run history, per-test evidence
  (redacted request/response, sandbox before/after diff, latency).

### EU AI Act compliance evidence

Add `--compliance` to any run:

```bash
agentaudit run agentaudit/packs/core --endpoint https://your-agent.example.com/chat --compliance
agentaudit report --run <run_id> --format compliance        # Markdown, grouped by EU article
agentaudit report --run <run_id> --format compliance-json   # machine-readable for GRC
```

Empty or all-skipped runs fail closed (`INCOMPLETE`) — no evidence is never treated as a
pass. This is technical readiness evidence, **not** a compliance/CE determination — see
[`docs/specs/compliance.md`](docs/specs/compliance.md).

## How it compares

| | agentaudit | promptfoo / garak | LLM-as-judge eval frameworks |
|---|---|---|---|
| Tests via | real endpoint (black-box) | real endpoint or API | usually needs the transcript |
| Checks | agent's **actions** on fake tools + what it said | mostly what it **said** | what it said, graded by another LLM |
| Compliance report | EU AI Act / ISO 42001 / NIST evidence built in | no | no |
| Attack/probe library breadth | narrower — two verticals + one attack pack | much broader (garak has 100+ probes) | varies |
| Maturity | MVP, one team | established, widely used | varies |

If you need broad, battle-tested prompt-injection/jailbreak probe coverage today, garak or
promptfoo cover more ground. agentaudit's edge is asserting on **side effects in a domain
sandbox**, not just grading the reply text, and turning that into a compliance-shaped report
— narrower scope, different axis of evidence. `core/adapters.py` normalizes promptfoo/garak
reports into agentaudit's schema so you can combine both.

## Limits

- **Windows: run pytest as a module, not a console script.** `uv run ... pytest` fails with
  `uv trampoline failed to canonicalize script path`; `uv run ... python -m pytest` runs the
  full suite green. `uv run` itself works fine — this is a console-script trampoline issue,
  not the package layout. `tools/validate.sh` already uses the module form.
- **No `examples/` directory.** It held only stale `.pyc` cache and was removed. Use the CLI
  commands above — they're the maintained, tested path.
- **No adaptive/iterative attack loop yet.** Tests run as a fixed, pre-selected set per run;
  branching into deeper multi-turn probes based on prior responses is on the roadmap below,
  not implemented.
- **Two demo verticals.** Treasury and email are real, working examples, not a general
  library of agent domains — adding a new one means writing a `Sandbox` subclass.

## Roadmap: adaptive assurance platform

The longer-term direction is `discover → profile → generate harness → select tests → attack
iteratively → score → report evidence` — automatically profiling an agent's risk surface and
adapting the attack based on what it learns, not just running a fixed pack. Steps 1–3 and 5
are implemented (`core/discovery.py`, `core/profile.py`, `core/catalog.py`,
`core/planner.py`, `reports/plan.py`); the adapters exist but don't yet execute promptfoo/
garak themselves, and the iterative attack loop is not built. See
[`docs/IMPLEMENTATION-TESTS-PLAN.md`](docs/IMPLEMENTATION-TESTS-PLAN.md) for the detailed
plan and [`CLAUDE.md`](CLAUDE.md#product-direction) for the current-repo-vs-target framing.

## Development

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, validation commands, PR checklist.
- [`docs/README.md`](docs/README.md) — documentation map (architecture, specs, diagrams,
  research, archived planning notes).
- [`docs/architecture.md`](docs/architecture.md) — control plane vs runner, execution modes,
  the privacy/redaction model, the sandbox model, deployment topology.
- [`docs/specs/`](docs/specs/README.md) — one contract spec per module.

```bash
pip install -e ".[dev]"
python -m pytest
```

## License

[Apache-2.0](LICENSE)
