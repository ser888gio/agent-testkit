---
id: quickstart
title: Quickstart
sidebar_position: 2
---

# Quickstart

This page runs your first audit in about two minutes.

## Step 1: pick a pack

A **pack** is a directory of YAML test files. Start with `core`: 20
domain-agnostic tests that only look at what the agent said, so they work
against any agent with no setup.

## Step 2: run it

```bash
agentaudit run core --endpoint https://your-agent.example.com/chat
```

Shipped packs are resolved by name, so this works from any directory. A pack
directory in your working directory wins over a shipped one of the same name,
and `core/prompt_injection` selects a single category.

`--endpoint` assumes the most common request shape: a `POST` with
`{"input": "..."}` that returns `{"text": "..."}`. If your agent differs, see
[Connect your agent](../guides/connect-your-agent.md).

## Step 3: read the result

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

Two numbers matter:

- **Pass rate** is the plain fraction of tests that passed.
- **Overall (weighted)** weights each test by its risk level, so one critical
  failure costs more than one low-risk failure. See [Scoring](../concepts/scoring.md).

The **exit code** is the CI gate. It is non-zero when the run falls below the
threshold or when a critical safety test fails.

## Step 4: get a report

Every run is saved to `database/agentaudit.db`. Render it in any supported format:

```bash
agentaudit report --run <run_id> --format md      # Markdown, good for PR comments
agentaudit report --run <run_id> --format html --out report.html
agentaudit report --run <run_id> --format junit   # for CI test reporting
```

## Step 5: open the dashboard

```bash
agentaudit ui
```

This serves a dashboard on `http://127.0.0.1:8000` with run history, a
pass/fail matrix, and per-test evidence — the redacted request and response, the
sandbox before/after diff, and latency.

## Endpoint requirements

Endpoints must use `https` and must be publicly routable. The egress policy
rejects loopback addresses and private IP ranges. To test an agent on your own
machine, set:

```bash
export AGENTAUDIT_EGRESS_ALLOW_LOCAL=1
```

## Try it without an agent

The repository ships demo agents so you can see a full run without wiring
anything up. Run these **from the repository root** — unlike packs, target
configs are plain file paths and are not resolved by name:

```bash
agentaudit run treasury --target agentaudit/config/treasury-agent.yaml
agentaudit run agentic  --target agentaudit/config/treasury-agent.yaml --compliance
```

## Next steps

- [Connect your agent](../guides/connect-your-agent.md) — auth headers and custom request shapes.
- [Choose a pack](../guides/choose-a-pack.md) — which tests apply to your agent.
- [CI integration](../guides/ci-integration.md) — make the gate block a merge.
