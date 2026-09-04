# agentaudit

Black-box testing for AI agents. Call the agent through its real endpoint, assert on what it
*said* and on what it *did* to fake tools around it, score the run, and gate CI on the exit
code.

Unlike output-grading evals, agentaudit checks side effects: "the agent said it wouldn't pay
the invoice, and the invoice store confirms it didn't." It needs no access to the agent's
prompts, tools, or source.

> Status: MVP. See [Limits](#limits).

## Quickstart

The `core` pack is 20 domain-agnostic tests — prompt injection, jailbreak, data leakage,
robustness, reliability, latency, response contract — and needs no sandbox.

```bash
git clone https://github.com/ser888gio/agent-testkit.git
cd agent-testkit
pip install -e .
agentaudit run core --endpoint https://your-agent.example.com/chat
```

```text
agentaudit run - target: your-agent.example.com   (20 tests)
CATEGORY              PASS  FAIL   ERR  SKIP
data_leakage             3     1     0     0
endpoint_contract        3     0     0     0
jailbreak                3     1     0     0
performance              1     0     0     0
prompt_injection         4     2     0     0
reliability              6     0     0     0
--------------------------------------------
Overall (weighted): 71%   Pass rate: 80%   Critical failures: 0
```

The exit code is non-zero when the run misses its threshold or a critical safety test fails.

Two constraints on the endpoint:

- `--endpoint` assumes `POST {"input": "..."}` returning `{"text": "..."}`. Any other shape,
  or auth headers, needs a [target config](#auth-headers-or-a-different-request-shape).
- It must be `https` and publicly routable. Loopback and private ranges are rejected unless
  `AGENTAUDIT_EGRESS_ALLOW_LOCAL=1` is set.

If `agentaudit` is not found after install, `pip` put the console script outside your `PATH`
(it says where in a `WARNING:` line). Either add that directory, or run
`python -m agentaudit.cli run ...` instead.

## Reports

Every run is saved to `database/agentaudit.db` (SQLite; `AGENTAUDIT_DB` overrides the path)
and can be re-rendered afterwards:

```bash
agentaudit report --run <run_id> --format md   # or: json, junit, html, compliance, plan
agentaudit ui                                  # dashboard at http://127.0.0.1:8000
```

`ui` binds to `127.0.0.1` with local dev auth. A non-loopback bind requires
`AGENTAUDIT_AUTH_MODE=oidc` and full OIDC config — see [`docs/keycloak.md`](docs/keycloak.md).

### EU AI Act evidence

`--compliance` on any run collects evidence grouped by regulatory obligation (EU AI Act,
ISO 42001, NIST):

```bash
agentaudit run core --endpoint https://your-agent.example.com/chat --compliance
agentaudit report --run <run_id> --format compliance        # Markdown, by EU article
agentaudit report --run <run_id> --format compliance-json   # for GRC tooling
```

Empty or all-skipped runs fail closed as `INCOMPLETE`. This is technical readiness evidence,
**not** a compliance or CE determination — see
[`docs/specs/compliance.md`](docs/specs/compliance.md).

## Auth headers or a different request shape

Write a target config instead of `--endpoint`:

```bash
cp agentaudit/config/my-agent.example.yaml agentaudit/config/my-agent.yaml
export AGENT_TOKEN=...
agentaudit run core --target agentaudit/config/my-agent.yaml
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
prompt goes, `text_path` is the dotted JSON path to the reply, and `${VAR}` interpolates env
vars at load time so tokens stay out of the file. Anything under `request` that `httpx`
accepts (`json`, `params`, `data`, `content`) is passed through.

## Which pack to run

`packs/core` asserts on what the agent *said*, so it applies to any agent. Start there.

The domain packs (`packs/treasury`, `packs/email`, `packs/agentic`) assert on what the agent
*did* to fake tools, so they need a matching `sandbox:` in the target config. Testing your
own payments or email agent means writing a `Sandbox` subclass for your tools — see the two
worked examples in [`backend/agentaudit/domains/`](backend/agentaudit/domains/).

## Commands

| Command | Purpose |
|---|---|
| `run <packs>` | Execute tests against a target; the exit code is the CI gate. `--plan` selects tests by profile first, `--external` also runs promptfoo/garak selections, `--attack` applies input transforms. |
| `plan <packs>` | Probe the target and print which tests would be selected or excluded, with reasons. |
| `report --run <id>` | Re-render a stored run as `json`, `md`, `html`, `junit`, `compliance`, `compliance-json` or `plan`. |
| `compare <a> <b>` | Diff two runs; exits non-zero when a previously-passing critical safety test regresses. |
| `evolve <packs>` | Generate candidate attacks with an attacker model into a human review queue. Off unless configured. |
| `worker` | Run the job-queue worker that executes runs enqueued from the dashboard. |
| `ui` | Serve the dashboard at `http://127.0.0.1:8000`. |
| `migrate` | Apply Alembic migrations to the SQLite store (`--status` to inspect). |
| `purge` | Delete runs older than `--keep-days` / beyond `--keep-last`, plus their artifacts. |

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./docs/diagrams/architecture-simplified-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./docs/diagrams/architecture-simplified-light.svg">
  <img alt="Architecture Overview" src="./docs/diagrams/architecture-simplified-light.svg">
</picture>

- **Agents** are called in-process (`CallableAgent`) or over HTTP (`HTTPAgent`); the same
  test suite runs against either.
- **Sandboxes** are fakes of the agent's tools — a bank + invoice store, an inbox + contacts
  + outbound ledger — so a test can check the payment was never wired.
- **Test packs are YAML**, not code: the core pack plus treasury, email, and an OWASP Agentic
  Top 10 pack (tool misuse, memory poisoning, goal hijack, privilege abuse).
- **Multi-turn attacks** escalate across turns (`crescendo`, `sequential`, `linear`,
  `bad_likert_judge`), deterministic and offline by default, with an optional attacker model
  and judge behind the same protocol.
- **Redaction is on by default**: secrets and PII are stripped from evidence before it is
  stored or displayed.
- **The dashboard** is org-scoped and multi-tenant: register an agent by URL, pick tests,
  cancel jobs, and browse the pass/fail matrix, per-test evidence, and history across runs.

[More diagrams →](./docs/diagrams/README.md) · [Architecture →](./docs/architecture.md)

## How it compares

| | agentaudit | promptfoo / garak | LLM-as-judge evals |
|---|---|---|---|
| Tests via | real endpoint (black-box) | real endpoint or API | usually needs the transcript |
| Checks | agent's **actions** on fake tools, plus what it said | mostly what it **said** | what it said, graded by another LLM |
| Compliance report | EU AI Act / ISO 42001 / NIST built in | no | no |
| Probe breadth | narrower — two verticals + one attack pack | much broader (garak has 100+ probes) | varies |
| Maturity | MVP, one team | established, widely used | varies |

For broad, battle-tested injection and jailbreak coverage today, garak and promptfoo cover
more ground — and `agentaudit run --external` runs them against your target alongside
agentaudit's own tests, normalizing their results into one report.

## Limits

- **Two demo verticals.** Treasury and email are working examples, not a general library of
  agent domains. A new one means writing a `Sandbox` subclass.
- **Generated tests need a human.** `evolve` output waits in a review queue; nothing
  model-written enters the audited baseline unreviewed.

## More

- [`examples/`](examples/) — three runnable quickstarts, including an offline demo where you
  can watch side-effect detection catch an unsafe agent.
- [`docs-web/`](docs-web/) — full user guide (install, concepts, CLI and assertion reference).
  Run locally with `cd docs-web && npm install && npm start`.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, validation, PR checklist.

## License

[Apache-2.0](LICENSE)
