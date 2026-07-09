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

## feat/runner

- **Sandbox registration ordering gotcha.** `agentkit.core.sandbox.SANDBOXES` only gets an
  entry once the module defining the `@register_sandbox(...)`-decorated class has actually
  been imported (e.g. `agentkit.domains.treasury.sandbox`). `runner.run()` calls
  `build_sandbox(target.sandbox)` *before* `build_agent(target, sandbox=sandbox)` — and it's
  `build_agent`'s dynamic `importlib.import_module(...)` of the callable's module that
  transitively imports the domain sandbox module (since `agent.py` imports `sandbox.py`).
  So calling `run()` as the very first touch of a domain (no prior import of
  `agentkit.domains.<x>.sandbox` or `.agent` anywhere in the process) raises
  `KeyError: unknown sandbox '<x>'; registered sandboxes: (none registered)` even though the
  sandbox is a real, correctly-decorated class — purely an import-order artifact, not a
  missing feature. Worked around in `tests/test_runner.py` by importing
  `agentkit.domains.treasury.sandbox` before calling `run()`. `feat/cli` (task 16) should
  eagerly import all `agentkit.domains.*` packages at startup (or `agentkit/domains/__init__.py`
  should import its submodules) so this can't bite a real CLI invocation.
