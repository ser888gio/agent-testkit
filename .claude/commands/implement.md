---
description: Execute an approved plan, staying within its scope.
argument-hint: [what to implement, or "the plan above"]
---

Implement: **$ARGUMENTS**

Follow the approved plan. If there is no plan in this session, stop and produce one first —
do not start editing from a bare description.

## Rules

- **Inspect before editing.** Read the file you are about to change and the nearest existing
  implementation of the same shape. This repo is heavily patterned; follow the precedent
  rather than inventing a new style.
- **Stay in the planned scope.** No drive-by renames, no reformatting untouched code, no
  "while I'm here" cleanups. If you find an unrelated bug, note it for the summary instead of
  fixing it.
- **Validate after each logical change**, narrowest first:
  `python -m pytest tests/test_<module>.py -k <name>`.
- **Never edit generated paths** — `dist/`, `agentaudit.egg-info/`, `agentaudit.db`,
  `uv.lock` (use `uv lock`), `docs/diagrams/*.svg` (re-render from `.d2`).
- **Respect the invariants:** the runner never raises; redaction runs before evidence is
  stored and again in `store.py`; no raw request/response logging; `core` imports nothing
  from `domains`/`reports`/`web`/`cli`; `httpx` only in `core/agent.py`; SQL only in
  `store.py`.
- **Explain before broadening.** If the change turns out to need materially more than
  planned, stop and say what you found and what it now requires — do not silently expand.

## Before declaring done

1. `bash tools/validate.sh` — full suite plus lint (~4s for tests; there is no reason to skip it)
2. Update `docs/components.yaml` if component boundaries, entry points, or dependencies changed
3. Re-read your own diff for accidental changes

## Summary

Report what changed (files and why), the validation you ran with its actual outcome, and
anything you deliberately left alone. If a command failed, say so with the output — never
report a check as passing that you did not run.
