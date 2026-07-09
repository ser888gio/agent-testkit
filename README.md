# agentkit

Black-box testing kit for AI agents. Test agents through their **endpoints** — the way
customers will actually expose them (no prompts, tools, orchestration, or source shared) —
and, where it matters, assert on the state of the **fake tools/services** the agent was
given (e.g. "was a payment actually created?").

> Status: MVP in progress. First demo vertical is **treasury/payment approval**.

## What it does (MVP)

- **Python SDK** — a normalized `Agent` adapter, a `Sandbox` interface, a `TestCase`/result
  schema, and a runner.
- **Two agent modes** — real black-box `HTTPAgent` (POST to an endpoint) and in-process
  `CallableAgent` (used by the demo agent and unit tests).
- **Sandbox side-effects** — fake bank + invoice store so tests can verify an agent
  *didn't* perform an unsafe action, not just what it said.
- **Built-in test packs** — action safety, prompt injection, data leakage, instruction
  following, reliability, performance.
- **SQLite results + web dashboard** — pass/fail matrix, run history, failed-test evidence.
- **CLI** — `agentkit run` (CI-gating exit codes) and `agentkit ui`.

## Quickstart (target state)

```bash
pip install -e .
agentkit run agentkit/packs --target agentkit/config/treasury-agent.yaml
agentkit ui   # dashboard at http://127.0.0.1:8000
```

## Development

See [`TASKS.md`](TASKS.md) for the task/branch plan and
[`docs/plan.md`](docs/plan.md) for the full MVP design.
