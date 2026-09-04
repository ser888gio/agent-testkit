---
id: choose-a-pack
title: Choose a pack
sidebar_position: 2
---

# Choose a pack

## Start with core

```bash
agentaudit run core --endpoint https://your-agent.example.com/chat
```

`packs/core` asserts only on what the agent said. It needs no sandbox and works
against any agent. Run it first — it will tell you whether the connection is
right and give you a baseline score.

## Then add a domain pack

Domain packs assert on what the agent *did*. They need a matching `sandbox:` in
your target config and only apply to agents in that domain.

| Your agent | Pack | Sandbox |
| --- | --- | --- |
| Handles payments, invoices, transfers | `packs/treasury` | `treasury` |
| Sends, forwards or reads mail | `packs/email` | `email` |
| Has real tools and real authority | `packs/agentic` | `treasury` |
| Something else | Write your own | Write your own |

## The agentic pack

`packs/agentic` covers the OWASP Agentic Top 10 and is grouped by attack class:

- `tool_misuse` — mass payout, splitting to evade a limit, tool metadata poisoning
- `goal_hijack` — injected payee, goal theft, recursive hijacking
- `privilege_abuse` — over-limit payout, role boundary, object-level authorization
- `memory_poisoning` — false pre-approval planted in context
- `human_oversight` — autonomous drift, missing approval token, excessive agency
- `code_execution` — shell tool abuse, SQL injection, server-side request forgery
- `agent_trust` — identity spoofing, relayed instruction

These are the tests that most often find something real, because they target the
gap between what an agent says and what it does.

## Filtering within a pack

Run a subset without editing files:

```bash
# Only one category
agentaudit run core --target my.yaml --category prompt_injection

# Only tests carrying a tag
agentaudit run core --target my.yaml --tag injection

# Just one subdirectory
agentaudit run agentic/tool_misuse --target my.yaml
```

Both `--category` and `--tag` can be repeated.

## Let the planner choose

For a large pack, the planner ranks tests by relevance to the profiled agent and
records why each was picked and what was left untested.

```bash
# See the plan without running anything
agentaudit plan treasury --target agentaudit/config/treasury-agent.yaml

# Run the top N ranked tests
agentaudit run treasury --target agentaudit/config/treasury-agent.yaml \
  --plan --max-tests 8
```

The plan is stored with the run, so `agentaudit report --run <id> --format plan`
shows the selection reasoning afterwards. This matters for an assurance
narrative: "we ran 8 of 40 tests" is only defensible if you can say which 32 you
skipped and why.

## How many packs at once

`agentaudit run` takes one pack directory. To run several, run several times and
compare, or point it at a parent directory containing the packs you want.
