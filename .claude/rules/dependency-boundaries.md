---
description: Allowed import directions between agentaudit layers
paths:
  - "backend/agentaudit/**/*.py"
  - "frontend/agentaudit/**/*.py"
  - "backend/agentaudit/cli.py"
---

# Dependency boundaries

The `agentaudit` package is one namespace package assembled from `./agentaudit`, `./backend`,
and `./frontend`. Import paths never contain `backend` or `frontend`.

Allowed directions (arrows point at what may be imported):

```text
cli  ──▶ core, reports, domains
web  ──▶ core, reports, domains
reports ──▶ core
domains ──▶ core.sandbox
core ──▶ (nothing else in agentaudit)
```

Verify with:

```bash
grep -rn "^from agentaudit\|^import agentaudit" backend/agentaudit/core --include="*.py"
```

Every hit must start `from agentaudit.core.` — anything else is a violation.

## Hard rules

- **`core` must not import `domains`, `reports`, `web`, or `cli`.** Domains are registered
  into `core` at runtime via the `@register_sandbox` decorator, not by `core` importing them.
- **`httpx` is imported in exactly one file:** `backend/agentaudit/core/agent.py`. This keeps
  the network boundary auditable. No other module may reach the network.
- **`reports` and `web` are control-plane:** they consume `RunResult`/`ScoreReport` and must
  not call an agent. `web`'s re-run endpoint invoking `core.runner.run` is the single
  documented exception; do not add a second one.
- **SQLite is reached only through `core/store.py:Store`.** No other module opens the
  database or issues SQL.

## Registration imports are load-bearing

`cli.py` and `web/app.py` contain `import agentaudit.domains.<name>.sandbox  # noqa: F401`
lines. They look like dead imports and are not — they trigger `@register_sandbox`. Removing
them makes `build_sandbox` fail with `unknown sandbox`. Leave the `noqa` in place.
