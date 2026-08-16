# agentkit

Black-box testing for AI agents: call the agent through its real endpoint, assert on what
it *said* and what it *did* to fake tools/services around it, score the run, and get a
report you can gate CI on.

**Who it's for:** teams shipping an AI agent (support bot, payments assistant, internal
copilot) who need to answer "does it still refuse to do the unsafe thing?" with evidence,
not vibes — before every merge, not just at launch.

**Why it exists:** most agent evaluation tools either grade free-text output or require
instrumenting the agent's internals. agentkit does neither: it treats the agent as a black
box (no prompts/tools/source shared) and checks the side effects against a fake sandbox —
"the agent said it wouldn't pay the invoice, and the invoice store confirms it didn't."

> Status: MVP. Two working demo verticals (treasury payment approval, email
> phishing/exfiltration), an OWASP Agentic Top 10 attack pack, and an EU AI Act / ISO 42001
> / NIST evidence report. See [Limits](#limits) before you rely on it.

## Try it in two minutes

```bash
git clone https://github.com/ser888gio/agent-testkit.git
cd agent-testkit
pip install -e .
agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml
```

```text
agentkit run - target: treasury-demo   (6 tests)
CATEGORY              PASS  FAIL   ERR  SKIP
action_safety            6     0     0     0
--------------------------------------------
Overall (weighted): 100%   Pass rate: 100%   Critical failures: 0
Gate: PASS
```

Exit code `0` — wire that into CI. Every run is persisted to `agentkit.db` (SQLite):

```bash
agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml --format json
agentkit report --run <run_id> --format md   # or: json, junit, html, compliance, plan
agentkit ui                                   # dashboard at http://127.0.0.1:8000
```

`agentkit ui` binds to `127.0.0.1` and enables local dev auth by default; a non-loopback
bind requires `AGENTKIT_AUTH_MODE=oidc` with full OIDC config. See
[`docs/keycloak.md`](docs/keycloak.md).

## Point it at your own agent

The treasury run above is a demo with fake tools. To test *your* agent, pass its URL.
`agentkit/packs/core` is 14 domain-agnostic tests — prompt injection, data leakage,
robustness, reliability, latency, response contract — that need no sandbox:

```bash
agentkit run agentkit/packs/core --endpoint https://your-agent.example.com/chat
```

```text
agentkit run - target: your-agent.example.com   (14 tests)
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

### When you need auth headers or a different request shape

Write a target config instead of `--endpoint`:

```bash
cp agentkit/config/my-agent.example.yaml agentkit/config/my-agent.yaml
# edit endpoint / request shape / response path, then:
export AGENT_TOKEN=...
agentkit run agentkit/packs/core --target agentkit/config/my-agent.yaml
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

Endpoints must be `https` and publicly routable — the egress policy
([`core/egress.py`](backend/agentkit/core/egress.py)) rejects loopback and private ranges
unless the worker sets `AGENTKIT_EGRESS_ALLOW_LOCAL=1`.

The domain packs (`packs/treasury`, `packs/email`, `packs/agentic`) assert on what the
agent *did* to fake tools, so they need a matching `sandbox:` and only apply to agents in
those domains. `packs/core` asserts on what the agent *said*, so it applies to any agent.

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
- **Regression gate** — `agentkit compare <run_a> <run_b>` diffs two runs and exits `1` if a
  previously-passing critical safety test now fails.
- **Reports** — JSON, JUnit XML, self-contained HTML, PR-comment Markdown, and an EU AI Act
  / ISO 42001 / NIST evidence report grouped by regulatory obligation.
- **SQLite store + dashboard** — pass/fail matrix, run history, per-test evidence
  (redacted request/response, sandbox before/after diff, latency).

### The email exfiltration demo

A vendor email tries to trick the agent into forwarding a payroll spreadsheet to an external
address:

```bash
agentkit run agentkit/packs/email --target agentkit/config/email-agent.yaml
```

### EU AI Act compliance evidence

```bash
agentkit run agentkit/packs/agentic --target agentkit/config/treasury-agent.yaml --compliance
agentkit report --run <run_id> --format compliance        # Markdown, grouped by EU article
agentkit report --run <run_id> --format compliance-json   # machine-readable for GRC
```

Empty or all-skipped runs fail closed (`INCOMPLETE`) — no evidence is never treated as a
pass. This is technical readiness evidence, **not** a compliance/CE determination — see
[`docs/specs/compliance.md`](docs/specs/compliance.md).

## How it compares

| | agentkit | promptfoo / garak | LLM-as-judge eval frameworks |
|---|---|---|---|
| Tests via | real endpoint (black-box) | real endpoint or API | usually needs the transcript |
| Checks | agent's **actions** on fake tools + what it said | mostly what it **said** | what it said, graded by another LLM |
| Compliance report | EU AI Act / ISO 42001 / NIST evidence built in | no | no |
| Attack/probe library breadth | narrower — two verticals + one attack pack | much broader (garak has 100+ probes) | varies |
| Maturity | MVP, one team | established, widely used | varies |

If you need broad, battle-tested prompt-injection/jailbreak probe coverage today, garak or
promptfoo cover more ground. agentkit's edge is asserting on **side effects in a domain
sandbox**, not just grading the reply text, and turning that into a compliance-shaped report
— narrower scope, different axis of evidence. `core/adapters.py` normalizes promptfoo/garak
reports into agentkit's schema so you can combine both.

## Limits

- **Windows: `uv run` is broken** (setuptools can't resolve the multi-root package layout).
  Use `python -m pytest` / `pip install -e .` directly, or `tools/validate.sh`, which probes
  for a working runner. CI (Linux) uses `uv run` and passes.
- **`examples/` scripts are currently missing** (only stale `.pyc` cache remains). Use the
  CLI commands above — they're the maintained path.
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
