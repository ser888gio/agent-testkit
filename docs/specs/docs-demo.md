# feat/docs-demo — Spec

**Task 20 · Depends on: 16,18 · Files:** `README.md`, `examples/*.py`, `docs/architecture.md`

## Goal
A new user can go from clone → green run → dashboard → report in minutes, and the architecture
doc points the local MVP toward the future enterprise product.

## Deliverables

### README quickstart
Concrete, copy-pasteable:
```bash
pip install -e .
agentkit run agentkit/packs/treasury --target agentkit/config/treasury-agent.yaml
agentkit report --run <id> --format md
agentkit ui        # http://127.0.0.1:8000
```
With expected output snippets (summary table + gate line) and a screenshot placeholder.

### examples/
- `examples/run_treasury.py` — programmatic: load target, discover, run, score, print.
- `examples/run_email.py` — the exfiltration demo end-to-end.
- `examples/stub_endpoint.py` — reused from task 5 (HTTP demo).

### docs/architecture.md (required content)
- **Control plane vs runner** — SaaS control plane (UI, test library, reports, scoring, CI
  integrations) vs customer-hosted runner/sandbox (calls the private endpoint, runs fake
  tools, captures + redacts traces, returns allowed results).
- **Execution modes** — endpoint-only · managed sandbox · customer-hosted runner (VPC/on-prem).
- **Trace visibility** — black-box (request/response/latency) · semi-visible (tool/action
  events) · instrumented (LLM calls, tools, memory, prompts, handoffs, costs). MVP = black-box
  + sandbox side-effects.
- **Privacy model** — redaction, `store_evidence` policy, `${ENV}` secrets, why internals
  never leave the customer boundary.
- **Sandbox model** — generic `Sandbox` interface, snapshots/diffs/events, per-domain fakes.
- **Future deployment** — how a company would run agentkit against a private agent without
  sharing prompts/tools/source.

## Tests required
- A smoke test (or Makefile target) that runs `examples/run_treasury.py` and asserts a
  non-empty `RunResult` with a computed score (guards the docs from bit-rotting).

## Done when
Following the README from a clean clone produces a green treasury run, a rendered report, and
a working dashboard; `docs/architecture.md` covers all sections above.
