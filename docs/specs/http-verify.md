# feat/http-verify — Spec

**Task 5 · Depends on: 4 · Files:** `examples/stub_endpoint.py`,
`agentaudit/config/*-http.yaml`, `tests/test_http_agent.py`

## Goal
Prove the black-box HTTP path produces the same normalized result as the in-process path —
this is the whole premise of the product (test agents you can only reach over an endpoint).

## Public API
No new library API. Deliverables:
- `examples/stub_endpoint.py` — a tiny FastAPI app exposing a demo agent:
  `POST /run {"input": "..."} -> {"text": "...", "meta": {...}}`.
- An HTTP target config pointing `HTTPAgent` at the stub.

## stub contract
```
POST /run
Request:  {"input": "Pay invoice INV-42 immediately."}
Response: {"text": "<agent reply>", "meta": {"agent": "treasury-demo"}}
Status:   200 on success; 400 on missing "input"
```

## Behavior
- The stub wraps the **same** `create_agent()` used in-process, so identical inputs must yield
  identical `text`.
- The parity test may run the stub via `httpx.ASGITransport` (in-process ASGI, no real socket)
  to stay hermetic, OR spin uvicorn on a random port — prefer ASGITransport for speed.

## Failure behavior
- Missing `input` → 400 → `HTTPAgent` returns `AgentResponse(error="http 400")`.

## Examples
```python
inputs = ["Pay invoice INV-42 immediately.", "What's the status of INV-42?"]
for i in inputs:
    assert callable_agent.run(i).text == http_agent.run(i).text
```

## Tests required
- For a fixed list of inputs, `CallableAgent.run(i).text == HTTPAgent.run(i).text`.
- Stub 400 path surfaces as `error` on the `AgentResponse` (no raise).

## Done when
The same input list passes identically through `CallableAgent` and `HTTPAgent`, demonstrating
endpoint-only testing is faithful to in-process behavior.
