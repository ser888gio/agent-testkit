---
description: Trace how a behavior, bug, feature, or component works. Read-only.
argument-hint: [behavior, bug, feature, or component]
---

Explore: **$ARGUMENTS**

**Do not edit any files during this workflow.** Investigation only.

Delegate the high-volume search to subagents rather than grepping broadly yourself:

- `architecture-explorer` — entry points and runtime flow
- `dependency-tracer` — consumers and blast radius
- `test-finder` — existing tests and the pattern to follow

Run them in parallel when their questions are independent.

Consult `docs/components.yaml` for the component map and `docs/specs/` for the relevant
module spec, but verify claims against the code — docs can drift.

## Report

1. **Entry points** — `path:symbol`
2. **Execution flow** — numbered, each step cited
3. **Domain rules and invariants** — what must stay true (e.g. runner never raises,
   redaction runs before evidence is stored)
4. **Persistence operations** — what touches `Store` / `agentkit.db`
5. **External calls** — anything leaving the process (`httpx` should appear only in
   `core/agent.py`)
6. **Relevant tests** — `tests/test_*.py::test_name`, plus any YAML packs in
   `agentkit/packs/` that reference the affected symbols by string name
7. **Affected components** — names from `docs/components.yaml`
8. **Confirmed findings vs open questions** — label every claim as one or the other

Cite a file path for every claim. End with the open questions that would change the shape of
a fix, rather than guessing at answers.
