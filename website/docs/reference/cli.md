---
id: cli
title: CLI reference
sidebar_position: 1
---

# CLI reference

```bash
agentaudit [--version] <command> [options]
```

If `agentaudit` is not on your `PATH`, use `python -m agentaudit.cli` instead.

## Common options

Most commands accept `--db <path>`. It defaults to `database/agentaudit.db` in the current
directory.

---

## `agentaudit run`

Run a pack against a target and apply the CI gate.

```bash
agentaudit run <pack> [options]
```

`<pack>` is either a path to a pack directory or the name of a shipped pack
(`core`, `treasury`, `email`, `agentic`). An existing directory relative to your
working directory always wins; otherwise the name is looked up in the installed
package, so `agentaudit run core` works from anywhere. Append a subdirectory to
narrow to one category, e.g. `core/endpoint_contract`. Set `AGENTAUDIT_PACKS` to
point the lookup at your own packs directory.

| Option | Default | Meaning |
| --- | --- | --- |
| `--target <path>` | — | Target config YAML. Use this or `--endpoint`. |
| `--endpoint <url>` | — | Shorthand target: `POST {"input": ...}` → `{"text": ...}`. |
| `--db <path>` | `database/agentaudit.db` | Where to persist the run. Overridden by `AGENTAUDIT_DB`. |
| `--fail-under <float>` | `0.0` | Minimum weighted score. Below this, exit `1`. |
| `--block-on-critical` / `--no-block-on-critical` | block | Whether a critical failure fails the gate. |
| `--tag <tag>` | — | Only run tests with this tag. Repeatable. |
| `--category <cat>` | — | Only run tests in this category. Repeatable. |
| `--format <fmt>` | `table` | `table` or `json`. |
| `--compliance` | off | Also compute the compliance evidence view. |
| `--attack <list>` | — | Comma-separated transforms to expand each test through. |
| `--plan` | off | Profile the target and run only the tests the plan justifies. |
| `--max-tests <n>` | — | Cap the number of tests. Use with `--plan`. |
| `--external` | off | Also run the third-party tools the plan selected. |

**Exit codes:** `0` gate passed · `1` gate failed · `2` usage or config error.

```bash
agentaudit run core --endpoint https://your-agent.example.com/chat
agentaudit run treasury --target agentaudit/config/treasury-agent.yaml \
  --fail-under 0.9 --category action_safety
```

### `--attack` transforms

Each transform rewrites the test's prompt and runs it as an extra variant, so one
test becomes several. Available transforms:

`base64`, `rot13`, `leetspeak`, `roleplay_wrap`, `unicode_confusable`,
`system_override`, `authority`, `json_embed`, `context_flood`, `multilingual`,
`poem`, `math_problem`, `permission_escalation`, `goal_redirect`,
`input_bypass`, `context_poison`, `synthetic_context`, `emotional`,
`character_stream`, `linguistic_confusion`.

```bash
agentaudit run core --target my.yaml --attack base64,roleplay_wrap
```

Test ids for variants are suffixed, for example `core.prompt_injection.x__rot13`.

:::caution `--external`
promptfoo and garak dial your endpoint themselves, so agentaudit's pinned address
does not constrain them. That is why the flag is opt-in. Do not enable it in a
pipeline unless you have thought about where those tools will send traffic.
:::

---

## `agentaudit plan`

Show which tests would run and why, without calling the agent.

```bash
agentaudit plan <packs_dir> [--target <path> | --endpoint <url>]
                [--max-tests <n>] [--format table|json]
```

Also validates every test file, so it is a fast syntax check for a pack you are
writing.

---

## `agentaudit report`

Render a stored run.

```bash
agentaudit report --run <run_id> [--format <fmt>] [--out <path>] [--db <path>]
```

| Format | Output |
| --- | --- |
| `json` (default) | Full machine-readable result. |
| `md` | Markdown summary, sized for a PR comment. |
| `html` | Self-contained HTML page. |
| `junit` | JUnit XML for CI test reporting. |
| `compliance` | Markdown grouped by regulatory obligation. |
| `compliance-json` | The same, machine-readable for a GRC tool. |
| `plan` | Why each test was selected, and what was left untested. |

Without `--out`, the content goes to stdout.

---

## `agentaudit compare`

Diff two runs. The regression gate.

```bash
agentaudit compare <run_id_a> <run_id_b> [--db <path>]
```

Exits `1` when a critical safety test that passed in run A fails in run B.

---

## `agentaudit ui`

Serve the dashboard.

```bash
agentaudit ui [--host 127.0.0.1] [--port 8000] [--db <path>]
```

Binding to loopback enables local development auth automatically. Binding to a
non-loopback address requires `AGENTAUDIT_AUTH_MODE=oidc` with full OIDC
configuration, and fails with exit `1` otherwise.

---

## `agentaudit evolve`

Generate new attacks against the target and keep the ones that are novel.

```bash
agentaudit evolve <packs_dir> [--target <path> | --endpoint <url>]
                  [--max-candidates 20] [--max-kept 10]
                  [--wall-clock 600] [--keep-runs <n>] [--dry-run]
```

Requires an attacker model. Set `AGENTAUDIT_ATTACKER_ENDPOINT` and
`AGENTAUDIT_ATTACKER_MODEL`. Any OpenAI-compatible endpoint works, including a
local Ollama, which keeps the whole campaign on your machine:

```bash
export AGENTAUDIT_ATTACKER_ENDPOINT=http://localhost:11434/v1/chat/completions
export AGENTAUDIT_ATTACKER_MODEL=llama3.1
```

Kept tests are **provisional**: they run for `--keep-runs` runs and then expire
unless a human promotes them into a pack. Use `--dry-run` to see candidates and
admission reasons without storing anything.

---

## `agentaudit migrate`

Apply database schema migrations.

```bash
agentaudit migrate [--db <path>] [--status]
```

`--status` lists pending migrations without applying them.

---

## `agentaudit purge`

Delete old runs and their artifact blobs.

```bash
agentaudit purge [--db <path>] [--keep-days <n>] [--keep-last <n>]
```

Pass at least one of `--keep-days` or `--keep-last`, otherwise it exits `2`.
`--keep-last` counts per agent.

---

## `agentaudit worker`

Run the job worker until interrupted. Same image as `ui`, different command.

```bash
agentaudit worker [--db <path>] [--poll-seconds 1.0]
                  [--lease-seconds 120] [--max-per-org 2]
```
