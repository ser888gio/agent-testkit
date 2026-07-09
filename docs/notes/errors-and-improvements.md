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
