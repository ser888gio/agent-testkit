# Contributing

## Setup

```bash
git clone https://github.com/ser888gio/agent-testkit.git
cd agent-testkit
pip install -e ".[dev]"
```

> `uv sync --extra dev` is the fastest way to a working environment (verified:
> after it, both `uv run ruff` and `uv run pytest` work on Windows). If your
> `pip` install puts console scripts off `PATH`, use `python -m pytest` /
> `python -m ruff`, or `bash tools/validate.sh`, which probes for a working
> runner automatically. CI (Linux) uses `uv run` and passes.

## Before opening a PR

```bash
python -m pytest              # full suite, ~350s measured on Windows
python -m ruff check .         # lint the whole repository
python -m ruff format .        # format
bash tools/validate.sh         # repo-wide lint + full suite; add --affected while iterating
```

Repo-wide lint (`ruff check .`) is green and CI enforces it — `tools/validate.sh`
lints everything for exactly that reason: a changed-files-only pass could let a
violation reach a red CI run unnoticed. Don't fold unrelated lint fixes into a
feature PR.

## Where things live

See [`CLAUDE.md`](CLAUDE.md) for the full repository map, architecture rules, and validation
ladder — it's the canonical guide for both human and AI contributors. Highlights:

- Test engine: `backend/agentaudit/core/`
- Domain sandboxes: `backend/agentaudit/domains/`
- Test content (YAML, not code): `agentaudit/packs/`
- Repo tests: `tests/`, one file per module (`tests/test_<module>.py`)

## Pull requests

- Keep PRs scoped to one change; don't mix refactors with features.
- Add or update tests for behavior you change — see `tests/` for the pattern closest to
  your change before writing a new one.
- Update `docs/specs/` if you change a public contract (schema, config, assertion
  registry).
- CI runs the full test suite and a security/dependency audit; both must pass before merge.

## Reporting issues

Use the issue templates under `.github/ISSUE_TEMPLATE/`. For anything security-sensitive,
see [`SECURITY.md`](SECURITY.md) instead of opening a public issue.
