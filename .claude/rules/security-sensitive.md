---
description: Redaction, evidence policy, and the dashboard's execution surface
paths:
  - "backend/agentaudit/core/redaction.py"
  - "backend/agentaudit/core/store.py"
  - "backend/agentaudit/core/runner.py"
  - "backend/agentaudit/core/config.py"
  - "frontend/agentaudit/web/app.py"
---

# Security-sensitive code

Changes to these files need explicit care and a passing `tests/test_security_p0.py` and
`tests/test_redaction.py`.

## Redaction

- `Redactor` strips API keys, bearer tokens, emails, IBANs, card numbers, account numbers,
  and phone numbers from any string/dict/list before it counts as evidence.
- It runs **twice on purpose**: in `runner.py` before a `TestResult` is built, and again in
  `store.py:save_run` before the SQLite write. Removing either pass because "the other one
  covers it" defeats the defense-in-depth design. Do not do it.
- Never add logging of a raw request or response. Not at DEBUG, not behind a flag.
- Adding a redaction pattern is safe and welcome; loosening or removing one is a security
  change that needs justification in the PR description.

## Evidence policy

`EvidencePolicy` (`store_request` / `store_response`) is an independent control from
redaction — it can drop evidence entirely (`None`) even after redaction. Both must be
honoured; neither substitutes for the other.

## Secrets in config

`TargetConfig` interpolates `${ENV_VAR}` at load time so tokens never sit in a committed
file. Never add a config field that expects a literal secret, and never write an example
config containing a real-looking credential.

## Dashboard execution surface

`frontend/agentaudit/web/app.py`'s re-run endpoint can load target/pack files and execute
Python test modules under the packs directory. Consequently:

- The default bind is `127.0.0.1`. Do not change the default.
- Any user-supplied path must stay constrained to the configured packs/config directories.
  Path traversal here is remote code execution.
- New endpoints that accept a path or a module name get the same scrutiny — flag them
  explicitly in your summary rather than treating them as routine.
