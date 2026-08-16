# feat/config — Spec

**Task 3 · Depends on: 1,2 · Files:** `agentaudit/core/config.py`, `agentaudit/config/*.yaml`,
`tests/test_config.py`

## Goal
Target configuration is a first-class module, not logic hidden in the runner. It says how to
reach an agent, which sandbox to bind, and the evidence/redaction policy.

## Public API
```python
class CallableSpec(BaseModel):
    type: Literal["callable"]
    callable: str                        # "module.path:factory" -> returns Agent-compatible fn

class HTTPSpec(BaseModel):
    type: Literal["http"]
    endpoint: str
    method: Literal["POST", "GET"] = "POST"
    headers: dict[str, str] = {}
    request: dict[str, Any] = {}         # template; {{ input }} placeholder(s)
    response: "ResponseSpec"
    timeout_s: float = 30.0

class ResponseSpec(BaseModel):
    text_path: str = "$.text"            # JSONPath to the agent's text reply

class TargetConfig(BaseModel):
    id: str
    agent: CallableSpec | HTTPSpec       # discriminated on `type`
    sandbox: str | None = None           # "treasury" | "email" | None
    evidence: EvidencePolicy = EvidencePolicy()   # from feat/redaction

def load_target(path: str | Path) -> TargetConfig     # YAML or JSON
```

## Config formats (authoritative examples)

Callable target:
```yaml
id: treasury-demo
agent:
  type: callable
  callable: agentaudit.domains.treasury.agent:create_agent
sandbox: treasury
evidence:
  store_request: true
  store_response: true
  redact:
    patterns:
      - name: api_key
        regex: "sk-[A-Za-z0-9_-]+"
```

HTTP target:
```yaml
id: treasury-http
agent:
  type: http
  endpoint: "http://localhost:8001/run"
  method: POST
  headers:
    Authorization: "Bearer ${AGENT_TOKEN}"
  request:
    json:
      input: "{{ input }}"
  response:
    text_path: "$.text"
  timeout_s: 10
sandbox: treasury
```

## Behavior
- `${ENV_VAR}` is interpolated from `os.environ` at load time (anywhere in the tree). Missing
  var → error naming the var. This keeps secrets out of files.
- `{{ input }}` is a **request-template** placeholder, left intact by config and rendered by
  the HTTPAgent (task 4) at call time — do not resolve it here.
- `agent` is a discriminated union on `type`; unknown type → validation error listing valid types.

## Failure behavior
- Missing `endpoint` for `type: http` → `ConfigError("http target 'id' requires endpoint")`.
- Unknown `sandbox` value → error listing registered sandboxes.
- Malformed YAML → error with file path + line if available.
- Missing env var for `${X}` → `ConfigError("env var X referenced by config 'id' is unset")`.

## Examples
```python
cfg = load_target("agentaudit/config/treasury-agent.yaml")
cfg.agent.type            # "callable"
cfg.evidence.store_request # True
```

## Tests required
- Load both example YAMLs → correct typed `TargetConfig`.
- `${AGENT_TOKEN}` interpolated from env; unset var raises clear error.
- http spec missing endpoint raises `ConfigError`.
- unknown sandbox raises with the list of valid names.

## Done when
`load_target` returns a validated `TargetConfig` for the shipped example configs, and every
invalid case above raises an actionable message.
