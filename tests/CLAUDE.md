# `tests/` — pytest suite

Tests for agentaudit itself. Do not confuse these with `agentaudit/packs/` (product test content
consumed by the loader).

## Conventions

- **One file per module:** `tests/test_<module>.py` mirrors `agentaudit/core/<module>.py`,
  `reports/`, `web/`, and each domain. Keep the mapping — it is how affected-scope selection
  in `tools/affected.sh` works.
- Shared helpers go in `tests/_fixtures.py`. It is deliberately named with a leading
  underscore so pytest does not collect it; import from it explicitly.
- There is no `examples/` directory; it was removed. If example scripts ever come back, they
  need coverage in this suite — the previous ones rotted precisely because nothing ran them.
- No `conftest.py` exists today. Add fixtures to `_fixtures.py` first; only introduce a
  `conftest.py` if a fixture genuinely needs pytest injection.

## test_migrate.py

Covers `agentaudit migrate` (the Alembic-backed CLI subcommand, `backend/agentaudit/cli.py`) and
`infra/alembic/versions/0001_baseline_schema.py`. Tests fresh and repeated application,
resuming from a partially-created baseline, and the captured pending/up-to-date status
output. Database assertions verify both the schema and Alembic revision state.

## Known collection warning

`agentaudit.core.schema.TestCase` triggers `PytestCollectionWarning` wherever it is imported —
pytest sees the `Test` prefix. This is expected and harmless. Do not rename the schema class
to silence it; it is a public contract.

## Integration-level coverage

There is no separate integration or e2e runner. These files are the integration layer and run
in the same suite:

- `tests/test_http_agent.py` — proves `HTTPAgent` and `CallableAgent` are behaviourally
  identical for the same input (the central premise of the product)
- `tests/test_web.py` — routes via Starlette `TestClient`
- `tests/test_cli.py` — CLI end to end
- `tests/test_security_p0.py` — security invariants; treat a failure here as blocking

## Expectations

- New behaviour needs a test in the file matching its module.
- Error and failure paths matter more than happy paths in this codebase — the runner's
  contract is that it never raises, which is only meaningful if the failure paths are tested.
- Prefer asserting on sandbox side effects over response text where both are available.

Run: `python -m pytest` (full suite, ~4s) or `-k <name>` while iterating.
