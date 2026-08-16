# Repository Guidelines

## Project Structure & Module Organization

`agentaudit` is a Python 3.10+ package with multiple source roots. Core execution code lives in `backend/agentaudit/core/`; domain adapters are under `backend/agentaudit/domains/`; reporting and CLI code live in `backend/agentaudit/reports/` and `backend/agentaudit/cli.py`. The FastAPI/Jinja dashboard is in `frontend/agentaudit/web/`. YAML configurations and reusable product test packs belong in `agentaudit/config/` and `agentaudit/packs/`. Keep Alembic migrations in `infra/alembic/`, documentation in `docs/`, and repository tests in `tests/`.

Import package modules as `agentaudit.*`, never `backend.agentaudit.*`. Observe any more specific guidance in the nearest `CLAUDE.md` when editing a subsystem.

## Build, Test, and Development Commands

- `uv sync --extra dev` installs locked runtime and development dependencies.
- `uv run --extra dev pytest` runs the complete pytest suite.
- `bash tools/validate.sh --affected` lints changed Python files and runs mapped tests for quick iteration.
- `bash tools/validate.sh` runs changed-file linting plus the full suite; use this before submitting.
- `uv build` produces wheel and source distributions in `dist/`.
- `uv run agentaudit ui` starts the dashboard at `http://127.0.0.1:8000`.

The validation scripts require Bash. CI tests Python 3.10 through 3.13 and builds the package.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations, and a 100-character line limit. Ruff enforces `E`, `F`, `I`, `B`, and `UP` rules; run `uv run ruff check <path>`. Use `snake_case` for modules, functions, and variables, `PascalCase` for classes, and descriptive lowercase YAML names such as `unauthorized_forward.yaml`. Preserve the dependency direction: `core` must not import domains, reports, web, or CLI code.

## Testing Guidelines

Tests use pytest. Mirror implementation modules with `tests/test_<module>.py`; place explicit shared helpers in `tests/_fixtures.py`. Cover failure paths, especially runner behavior and redaction. Prefer assertions on sandbox side effects over response wording. Treat failures in `tests/test_security_p0.py` as release blockers. No fixed coverage percentage is configured, but every behavior change requires focused regression coverage and a full-suite run.

## Commit & Pull Request Guidelines

History favors concise subjects, sometimes prefixed by a task ID (`T2: org_id on every row`). Use an imperative, scoped summary and avoid mixing unrelated work. Pull requests should explain motivation and verification, link relevant issues, and include screenshots for dashboard changes. Before merge, obtain approval, resolve review conversations, update the branch, and pass `CI / Required` plus `Security / Dependency audit`.
