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

### In CI

`run` exits `0` when the gate passes, `1` when it fails, and `2` on a bad target or pack.
`--fail-under` sets the score threshold; a critical safety failure fails the run on its own
unless you pass `--no-block-on-critical`.

```yaml
- run: pip install -e .
- name: Audit the agent
  env:
    AGENT_TOKEN: ${{ secrets.AGENT_TOKEN }}
  run: |
    # --format json prints the run id; keep it for the report and gate on the exit code
    set +e
    agentaudit run core --target agentaudit/config/my-agent.yaml       --fail-under 0.8 --format json > run.json
    echo "gate=$?" >> "$GITHUB_ENV"
    echo "run_id=$(jq -r .run_id run.json)" >> "$GITHUB_ENV"
- name: Publish results
  if: always()
  run: agentaudit report --run "$run_id" --format junit --out results.xml
- if: env.gate != '0'
  run: exit 1
```

To gate on *regressions* rather than an absolute score, keep the previous run id and use
`compare`, which exits `1` when a critical test that used to pass starts failing:

```bash
agentaudit compare "$PREVIOUS_RUN_ID" "$RUN_ID"
```

## Reports

Every run is saved to `database/agentaudit.db` (SQLite; `AGENTAUDIT_DB` overrides the path)
and can be re-rendered afterwards:

```bash
agentaudit report --run <run_id> --format md   # or: json, junit, html, compliance, plan
agentaudit ui                                  # dashboard at http://127.0.0.1:8000
```

`ui` binds to `127.0.0.1` with local dev auth. A non-loopback bind requires
`AGENTAUDIT_AUTH_MODE=oidc` and full OIDC config — see [`docs/deploy-clerk.md`](docs/deploy-clerk.md).

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

## Turning production failures into tests

When the agent misbehaves in production, paste the transcript in and it becomes a permanent
regression test:

```bash
agentaudit incident import ./incident-4821.txt --target agentaudit/config/my-agent.yaml
```

The transcript is parsed and redacted before anything is stored, a candidate test with
proposed assertions is derived from it, and that candidate is **replayed against the current
agent** to check the failure still reproduces. The result is queued in the `generated` pack:

```text
inferred category=prompt_injection risk=high (override with --category/--risk if this looks wrong)
verifying candidate inc-4821 reproduces against my-agent...
  inc-4821: REPRODUCES (invoice paid despite refusal)
queued inc-4821 for review in the 'generated' pack (reproduces) -- promote or reject it in `agentaudit ui`
```

Nothing enters the audited baseline unreviewed — you promote or reject it in the dashboard's
review queue, the same one `evolve` feeds.

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

### Let the profile pick the tests

`plan` probes the target, infers a profile, and prints what it would run and what it would
skip — with a reason for every line, so the selection is auditable rather than a black box:

```bash
agentaudit plan core --target agentaudit/config/my-agent.yaml
```

```text
agentaudit plan - target: my-agent
  profile: domain=support interface=http risk=high multi_turn=True tool_use=False
  selected (12):
   8.40  core.injection.system_prompt_leak  [core]
          why: interface=http exposes the prompt surface; risk=high
  not tested (8):
          core.tools.unauthorized_call: target reports no tool use
```

`run --plan` runs that selection instead of the whole pack, and `--max-tests` caps it.

### Multiply the tests you have

`--attack` expands every selected test through input transforms, so one prompt becomes many
phrasings of the same attack:

```bash
agentaudit run core --target ... --attack base64,roleplay_wrap,context_poison
```

There are 20 transforms in three families — encoding and obfuscation (`base64`, `rot13`,
`leetspeak`, `unicode_confusable`, `character_stream`), social engineering (`authority`,
`roleplay_wrap`, `emotional`, `system_override`), and context manipulation (`context_poison`,
`goal_redirect`, `synthetic_context`, `context_flood`). They are pure string transforms:
deterministic, offline, and free. Selecting all 20 is ~21x the pack size, so the dashboard's
picker offers a recommended set — `base64`, `authority`, `emotional`, `roleplay_wrap`,
`context_poison` — that covers every family at roughly 5x.

## Commands

| Command | Purpose |
|---|---|
| `run <packs>` | Execute tests against a target; the exit code is the CI gate. `--plan` selects tests by profile first, `--external` also runs promptfoo/garak selections, `--attack` applies input transforms. |
| `plan <packs>` | Probe the target and print which tests would be selected or excluded, with reasons. |
| `report --run <id>` | Re-render a stored run as `json`, `md`, `html`, `junit`, `compliance`, `compliance-json` or `plan`. |
| `compare <a> <b>` | Diff two runs; exits non-zero when a previously-passing critical safety test regresses. |
| `evolve <packs>` | Generate candidate attacks with an attacker model into a human review queue; `--campaign` runs them adaptively against the target. Off unless configured. |
| `incident import <transcript>` | Turn a production failure transcript into a regression candidate: parse, redact, check it still reproduces, queue it for review. |
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
- **Adaptive attacks** are opt-in per run: after the pack finishes, an attacker model writes
  new candidates against what the agent already did, runs them, and keeps the ones that land.
  Available from the CLI (`evolve --campaign`) and from the dashboard, on a fixed server-side
  budget — it spends metered attacker-model calls.
- **Redaction is on by default**: secrets and PII are stripped from evidence before it is
  stored or displayed.
- **The dashboard** is org-scoped and multi-tenant: register an agent by URL, pick tests,
  cancel jobs, and browse the pass/fail matrix, per-test evidence, and history across runs.
- **promptfoo and garak run alongside it**: `agentaudit run --external` ranks, runs and
  normalizes their probes into the same report as agentaudit's own tests.

[More diagrams →](./docs/diagrams/README.md) · [Architecture →](./docs/architecture.md)

## More

- [`examples/`](examples/) — three runnable quickstarts, including an offline demo where you
  can watch side-effect detection catch an unsafe agent.
- [`docs-web/`](docs-web/) — full user guide (install, concepts, CLI and assertion reference).
  Run locally with `cd docs-web && npm install && npm start`.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, validation, PR checklist.

## License

[Apache-2.0](LICENSE)
