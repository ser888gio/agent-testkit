---
id: limits
title: Limits and roadmap
sidebar_position: 6
---

# Limits and roadmap

agentaudit is an MVP. This page is the honest account of what it does not do, so
you can decide what to rely on it for.

## What it does not do

**No general library of agent domains.** Treasury and email are real, working
examples, not a catalog. Testing a different domain means writing a `Sandbox`
subclass yourself. See [Add a sandbox](./guides/add-a-sandbox.md).

**Narrower probe library than the specialists.** garak ships more than a hundred
probes. If broad, battle-tested prompt-injection and jailbreak coverage is what
you need today, garak or promptfoo cover more ground. agentaudit's edge is a
different axis — side effects in a domain sandbox — not breadth.

**The iterative attack loop is partial.** Adaptive tests escalate along scripted
ladders, and `refine: true` lets an attacker model write turns. But full
branching, where the tool explores several attack paths and mutates based on what
it learns across tests, is not built.

**Isolation is killability, not containment.** Each run spawns a sandbox
supervisor and a nested agent worker so a hung or misbehaving run can be killed.
That is not a security boundary. Do not treat it as a container for untrusted
code.

**Compliance output is evidence, not a determination.** It shows which technical
controls were exercised and what happened. It does not make a system conformant
and is not a CE marking assessment.

## How it compares

|  | agentaudit | promptfoo / garak | LLM-as-judge frameworks |
| --- | --- | --- | --- |
| Tests via | Real endpoint, black box | Real endpoint or API | Usually needs the transcript |
| Checks | Actions on fake tools, plus text | Mostly text | Text, graded by another model |
| Compliance report | Built in | No | No |
| Probe breadth | Narrower | Much broader | Varies |
| Maturity | MVP, one team | Established | Varies |

The tools are complementary. `core/adapters.py` normalizes promptfoo and garak
reports into agentaudit's schema, so you can run both and merge the evidence.

## Known environment issues

**Windows: run pytest as a module.** `uv run --frozen --extra dev pytest` fails
with `uv trampoline failed to canonicalize script path`. The module form works:

```bash
uv run --frozen --extra dev python -m pytest
```

This is a console-script trampoline issue, not the package layout.

**Runs are slow relative to the assertion work.** Each `runner.run` call spawns a
supervisor and a worker process, which costs roughly 2.5 seconds on Windows.
Production pays that once per run. The repository's own test suite calls `run`
dozens of times, which is why the full suite takes 3 to 6 minutes.

**No type checker.** The repository does not configure one.

## Roadmap

The target loop is:

```
discover -> profile -> generate harness -> select tests -> attack iteratively -> score -> report
```

| Stage | Status |
| --- | --- |
| Discover the endpoint shape | Shipped |
| Profile the agent into an `AgentProfile` | Shipped |
| Test catalog with explainable ranking | Shipped |
| Planner that records why each test was chosen | Shipped |
| Reporting that explains selection | Shipped |
| Adapter execution: run promptfoo and garak, merge evidence | Shipped, opt-in via `--external` |
| Iterative attack loop with branching and retries | Not built |

The framing to keep in mind: this repository is the execution and evidence core
of a larger adaptive agent assurance platform, not the finished platform.
