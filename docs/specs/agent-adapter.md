# feat/agent-adapter — Spec

**Task 4 · Depends on: 1,3 · Files:** `agentaudit/core/agent.py`, `tests/test_agent.py`

## Goal
One normalized interface the runner + assertions code against, regardless of how the agent
is reached.

## Public API
```python
@dataclass
class AgentResponse:
    text: str                    # normalized text reply ("" if none)
    raw: Any = None              # full underlying payload (dict for http, native for callable)
    latency_ms: float | None = None
    status_code: int | None = None    # http only
    error: str | None = None     # set on failure; text may be ""
    def contains_any(self, needles: list[str]) -> bool   # case-insensitive
    def contains_all(self, needles: list[str]) -> bool

class Agent(Protocol):
    def run(self, input: str | dict) -> AgentResponse: ...

class CallableAgent(Agent):
    def __init__(self, fn: Callable[..., Any], sandbox=None): ...

class HTTPAgent(Agent):
    def __init__(self, spec: HTTPSpec): ...      # from feat/config

def build_agent(config: TargetConfig, sandbox=None) -> Agent   # factory on config.agent.type
```

## Behavior
- **Latency**: measured around the call with `time.perf_counter()`, in ms, always set (even
  on error).
- **CallableAgent**: imports `module:factory` (from config), calls it to get the callable,
  invokes `fn(input, sandbox=sandbox)` if it accepts `sandbox`, else `fn(input)`. Wraps the
  return: if already `AgentResponse`, pass through; if `str`, `AgentResponse(text=...)`; if
  `dict`, map `text` key and keep whole dict as `raw`.
- **HTTPAgent**: renders `request` template replacing `{{ input }}` with the test input,
  sends via `httpx` with `timeout=spec.timeout_s`, extracts `text` via `response.text_path`
  (JSONPath), sets `status_code`, keeps parsed body as `raw`.

## Failure behavior (do not raise; return AgentResponse)
- HTTP 4xx/5xx → `AgentResponse(text="", status_code=code, error="http {code}", raw=body)`.
- Network/connection exception → `AgentResponse(error=str(exc))`.
- Timeout → `AgentResponse(error="timeout")`.
- `text_path` misses → `text=""`, `error="response_path_not_found"`, `raw` still populated.
- The runner (task 11) decides pass/fail/error from `error` + assertions; the adapter's job
  is to never throw.

## Examples
```python
a = CallableAgent(lambda s: f"echo: {s}")
r = a.run("hi"); r.text          # "echo: hi"; r.latency_ms is not None

# HTTP against a stub returning {"text": "ok"}
h = HTTPAgent(spec); h.run("hi").text   # "ok"; status_code == 200
```

## Tests required
- `CallableAgent` normalizes str / dict / `AgentResponse` returns; passes `sandbox` when
  accepted.
- `HTTPAgent` happy path via `httpx.MockTransport` returning `{"text": "ok"}`.
- HTTP 500 → `error="http 500"`, no raise. Timeout (mock raising `TimeoutException`) →
  `error="timeout"`. Missing `text_path` → `error="response_path_not_found"`.
- `contains_any`/`contains_all` are case-insensitive.

## Done when
Both adapters return a populated `AgentResponse`; all failure modes yield an
`AgentResponse` with `error` set and never raise; HTTP path is unit-tested fully offline.
