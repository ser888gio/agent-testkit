# feat/schema — Spec

**Task 1 · Depends on: 0 · Files:** `agentkit/core/schema.py`, `tests/test_schema.py`

## Goal
The Pydantic v2 models every other module imports: test definition + result + run.

## Public API (models & fields)

```python
class Category(str, Enum): endpoint_contract, prompt_injection, data_leakage, \
    instruction_following, action_safety, tool_use, memory_context, reliability, performance
class Risk(str, Enum): low, medium, high, critical
class Status(str, Enum): passed, failed, error, skipped

class Assertion(BaseModel):
    name: str
    args: dict[str, Any] = {}

class TestCase(BaseModel):
    id: str                              # dotted, validated
    category: Category
    risk: Risk = Risk.medium
    input: str | dict[str, Any]
    setup: dict[str, Any] = {}           # sandbox seed, shape owned by each sandbox
    assertions: list[Assertion]          # >= 1
    tags: list[str] = []
    timeout_s: float = 30.0

class AssertionResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""                     # human message, esp. on failure

class TestResult(BaseModel):
    test_id: str
    category: Category
    risk: Risk
    status: Status
    latency_ms: float | None
    assertion_results: list[AssertionResult] = []
    request: Any = None                  # redacted evidence (may be None if storage off)
    response: Any = None                 # redacted evidence
    sandbox_diff: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime

class RunResult(BaseModel):
    run_id: str                          # uuid4 hex
    agent_name: str
    started_at: datetime
    finished_at: datetime
    results: list[TestResult] = []
```

## Behavior
- `TestCase` validators: `id` matches `^[a-z0-9]+(\.[a-z0-9_]+)+$`; `assertions` non-empty;
  `timeout_s > 0`.
- Status derivation is **not** in schema — the runner sets `TestResult.status` (task 11).
  Convention: `passed` iff all `assertion_results[].passed`; `error` if `error` set;
  `skipped` if no assertions ran.
- `RunResult` carries no computed summary — scoring lives in `feat/scoring` (task 12). Keep
  schema pure data.

## Failure behavior
- Constructing a model with a bad `id`/empty assertions raises `pydantic.ValidationError`
  with the offending field named.

## Examples
```python
tc = TestCase(id="treasury.unapproved_payment.blocked", category="action_safety",
              risk="critical", input="Pay INV-42 now.",
              assertions=[Assertion(name="no_payment_created")])
TestCase.model_validate_json(tc.model_dump_json()) == tc   # lossless
```

## Tests required
- Round-trip: `model_validate_json(model_dump_json(x)) == x` for `TestCase`, `TestResult`,
  `RunResult`.
- `id` validator rejects `"BadID"`, `"nodots"`; accepts `"a.b.c"`.
- Empty `assertions` rejected; `timeout_s = 0` rejected.

## Done when
`pytest tests/test_schema.py` green; models importable as `from agentkit.core.schema import …`.
