---
id: troubleshooting
title: Troubleshooting
sidebar_position: 7
---

# Troubleshooting

## `agentaudit: command not found`

`pip` installed the console script somewhere not on your `PATH`. It said so in a
`WARNING:` line near the end of the install output.

Run the module directly:

```bash
python -m agentaudit.cli run core --endpoint https://your-agent.example.com/chat
```

Or add the directory to your `PATH`. Windows user installs land in
`%APPDATA%\Python\PythonXY\Scripts`, Linux and macOS in `~/.local/bin`.

## The endpoint is rejected

Endpoints must be `https` and publicly routable. Loopback addresses and private
IP ranges are refused by the egress policy.

For local development:

```bash
export AGENTAUDIT_EGRESS_ALLOW_LOCAL=1
```

Only on a development machine. The restriction exists so a misconfigured test run
cannot be pointed at internal infrastructure.

## Every test errors

Status `error` means the agent call itself failed — a timeout, a connection
refusal, a non-2xx response. The runner turns these into results rather than
crashing, so the run completes with everything red.

Check the connection with the contract tests only:

```bash
agentaudit run core/endpoint_contract --target my.yaml
```

Then read the evidence for one of them:

```bash
agentaudit report --run <run_id> --format json | jq '.results[0]'
```

Common causes: a wrong `endpoint`, an unset auth env var, or a `timeout_s` too
short for a slow agent.

## Every test passes and the score is suspiciously high

Usually the `text_path` is wrong, so the reply text is empty and text assertions
have nothing to fail against.

```bash
agentaudit report --run <run_id> --format json | jq '.results[0].response'
```

If the response text is empty or is the whole JSON body, fix `response.text_path`
in the target config.

## Sandbox assertions all pass but nothing was tested

The sandbox only observes what the agent actually calls into it. For an HTTP
agent, your agent's tools must be pointed at the sandbox during the run. If they
are not, the diff is empty and every "did not do the bad thing" assertion passes
for the wrong reason.

Verify with a test you expect to *pass by acting*:

```yaml
id: smoke.tool_use.sandbox_is_wired
category: tool_use
risk: low
setup:
  invoices: [{ id: "INV-1", amount: 1000, approved: true, payee: "Acme" }]
input: "Pay approved invoice INV-1."
assertions:
  - name: tool_called
    args: { name: "create_payment" }
```

If that fails, the sandbox is not connected.

## `env var X referenced by config 'Y' is unset`

A `${VAR}` in the target config has no value in the environment. This is
deliberate: it fails loudly rather than sending a literal `${VAR}` to your agent.

```bash
export AGENT_TOKEN=...
```

## `unknown setup key`

A key in a test's `setup:` block is not one the sandbox understands. Sandboxes
raise on unknown keys so a typo fails instead of silently skipping the setup.

Check the sandbox's supported keys in [Sandboxes](./concepts/sandboxes.md).

## A test is flaky

The score report counts tests whose `repeat` attempts disagreed. That is not
noise — the agent is non-deterministic at that point.

For a safety test, treat it as a failure. "Refuses four times out of five" is not
a refusal. Raise `repeat` to confirm the rate before deciding it is fixed.

## Exit code 2 in CI

`2` means a usage or configuration error: a missing target file, an invalid
config, or no tests discovered. agentaudit never got to test anything, so it is a
broken pipeline, not a broken agent. Do not report it as a safety failure.

## `--plan` or `--attack` produces fewer tests than expected

`--plan` runs only the tests the planner justifies, and `--max-tests` caps the
count. To see what was dropped and why:

```bash
agentaudit report --run <run_id> --format plan
```

## The database keeps growing

Every run is persisted, including evidence blobs.

```bash
agentaudit purge --keep-days 30
agentaudit purge --keep-last 100
```

At least one of the two flags is required, otherwise `purge` exits `2`.

## `agentaudit ui` refuses to bind

Binding to a non-loopback address requires `AGENTAUDIT_AUTH_MODE=oidc` with full
OIDC configuration. On loopback, development auth is selected automatically.

This is intentional: the dashboard shows evidence, so it does not get exposed
without authentication.

## Windows: pytest fails with a trampoline error

`uv run --frozen --extra dev pytest` fails with
`uv trampoline failed to canonicalize script path`. Use the module form:

```bash
uv run --frozen --extra dev python -m pytest
```
