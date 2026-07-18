---
description: Allowed import directions between agentkit layers
paths:
  - "backend/agentkit/**/*.py"
  - "frontend/agentkit/**/*.py"
  - "backend/agentkit/cli.py"
---

# Dependency boundaries

The `agentkit` package is one namespace package assembled from `./agentkit`, `./backend`,
and `./frontend`. Import paths never contain `backend` or `frontend`.

Allowed directions (arrows point at what may be imported):

```text
cli  ──▶ core, reports, domains
web  ──▶ core, reports, domains
reports ──▶ core
domains ──▶ core.sandbox
core ──▶ (nothing else in agentkit)
```

Verify with:

```bash
grep -rn "^from agentkit\|^import agentkit" backend/agentkit/core --include="*.py"
```

Every hit must start `from agentkit.core.` — anything else is a violation.

## Hard rules

- **`core` must not import `domains`, `reports`, `web`, or `cli`.** Domains are registered
  into `core` at runtime via the `@register_sandbox` decorator, not by `core` importing them.
- **`httpx` is imported in exactly one file:** `backend/agentkit/core/agent.py`. This keeps
  the network boundary auditable. No other module may reach the network.
- **`reports` and `web` are control-plane:** they consume `RunResult`/`ScoreReport` and must
  not call an agent. `web`'s re-run endpoint invoking `core.runner.run` is the single
  documented exception; do not add a second one.
- **SQLite is reached only through `core/store.py:Store`.** No other module opens the
  database or issues SQL.

## Registration imports are load-bearing

`cli.py` and `web/app.py` contain `import agentkit.domains.<name>.sandbox  # noqa: F401`
lines. They look like dead imports and are not — they trigger `@register_sandbox`. Removing
them makes `build_sandbox` fail with `unknown sandbox`. Leave the `noqa` in place.
