# Errors & Improvements Log

Running notes on issues found while implementing the branch plan. Not blocking, but
worth a look during `feat/docs-demo` cleanup or a later pass.

## feat/schema

- `pytest` emits `PytestCollectionWarning: cannot collect test class 'TestCase'/'TestResult'
  because it has a __init__ constructor` when collecting `tests/test_schema.py`. This is
  because Pydantic model classes named `TestCase`/`TestResult` match pytest's default
  `Test*` collection prefix. Harmless (pytest correctly skips them), but could be silenced
  with a `pyproject.toml` `[tool.pytest.ini_options] python_classes = "X*"` tweak or a
  `conftest.py` filter if the warning noise bothers CI logs.

## feat/http-verify

- `tests/test_http_agent.py` uses `fastapi.testclient.TestClient` (not `httpx.ASGITransport`
  directly) because `HTTPAgent` calls the synchronous `httpx.request(...)`, and
  `ASGITransport` only implements the async transport interface — a bare `httpx.Client`
  raises `AttributeError: 'ASGITransport' object has no attribute '__enter__'`. `TestClient`
  wraps the same ASGI app synchronously via a portal, so it's an equally hermetic swap-in,
  but it emits a `DeprecationWarning` because `HTTPAgent` always passes `timeout=` through to
  `client.request(...)` and `TestClient` warns on that. Cosmetic only (test-only code path);
  worth revisiting if `TestClient`'s `timeout` handling changes in a future starlette release.
