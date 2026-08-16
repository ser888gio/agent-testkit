# feat/runner — Spec

**Task 11 · Depends on: 4,6,9,10 · Files:** `agentaudit/core/runner.py`, `tests/test_runner.py`

## Goal
The execution lifecycle: turn a target + a set of tests into a `RunResult`, deterministically
and without ever crashing.

## Public API
```python
def run(target: TargetConfig, tests: list[TestCase],
        *, redactor: Redactor | None = None) -> RunResult
def run_one(agent: Agent, sandbox: Sandbox | None, test: TestCase,
            redactor: Redactor) -> TestResult
```

## Lifecycle (exact order, per test)
```
for test in tests:
    started = now()
    sandbox.reset()                         # if sandbox bound
    sandbox.apply_setup(test.setup)
    before = sandbox.snapshot()
    response = agent.run(test.input)        # under test.timeout_s
    after  = sandbox.snapshot()
    diff   = sandbox.diff(before, after)
    ctx    = AssertionContext(response, sandbox, response.latency_ms, diff, {})
    results = [evaluate(a, ctx) for a in test.assertions]
    status  = derive_status(response, results)
    request, response_evidence = redact_evidence(target.evidence, redactor,
                                                  test.input, response)
    yield TestResult(..., status, latency_ms, results, request, response_evidence,
                     sandbox_diff=diff, error=response.error, started, finished=now())
```

## Status derivation
- `error` — `response.error` is set (network/timeout/http/adapter), OR a Python test raised a
  non-assertion exception.
- `failed` — no agent error, but ≥1 assertion `passed=False`.
- `passed` — no agent error and all assertions passed.
- `skipped` — test explicitly marked skip (e.g. `tags` contains `skip`, or no assertions).

## Rules
- **Timeout**: enforce `test.timeout_s` around `agent.run`. On timeout → the response is
  `AgentResponse(error="timeout")` → status `error`. (Adapter already returns timeout as
  error for HTTP; for callable, wrap with a timeout guard.)
- **Isolation**: `sandbox.reset()` before *every* test — no state leaks between tests.
- **Continue on failure**: a failed/errored test never stops the run; remaining tests run.
- **Evidence**: request/response stored only if `evidence.store_*`, always passed through the
  `Redactor` first. If storage off → field is `None`.
- **No sandbox**: `before/after/diff` are `None`; sandbox assertions fail gracefully.

## Failure behavior
- Any exception inside `run_one` (that isn't already captured) is caught → `TestResult` with
  `status=error`, `error=str(exc)`. `run` always returns a complete `RunResult`.

## Examples
```python
rr = run(cfg, discover("agentaudit/packs/treasury"))
{r.status for r in rr.results}          # {passed, failed} (or error on a broken target)
```

## Tests required
- Mixed pack (one passing, one failing-assertion, one erroring agent, one skipped) → exactly
  those four statuses.
- Timeout: a slow callable exceeding `timeout_s` → `error` with `error=="timeout"`.
- Sandbox reset isolation: a payment in test A does not appear in test B's snapshot.
- Evidence: `store_response=False` → `TestResult.response is None`; secrets in input are
  redacted in stored `request`.

## Done when
`run` returns a full `RunResult` for a mixed pack with correct per-status classification,
enforced timeouts, per-test sandbox isolation, and redacted evidence — and never raises.
