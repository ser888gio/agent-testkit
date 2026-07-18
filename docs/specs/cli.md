# feat/cli — Spec

**Task 16 · Depends on: 11,12,13 · Files:** `agentkit/cli.py`, `tests/test_cli.py`

## Goal
The operator surface: run tests (with CI-gating exit codes), export reports, launch the UI.
Built with **Typer**; entrypoint `agentkit = "agentkit.cli:app"` (already in pyproject).

## Commands

### `agentkit run`
```
agentkit run <packs_dir> --target <config.yaml> [--db agentkit.db]
             [--fail-under 0.8] [--no-block-on-critical]
             [--tag t] [--category c] [--format table|json]
```
Flow: `load_target` → `discover(packs_dir)` (+ filters) → `run` → `score` →
`store.save_run` → print summary → exit.

Output (table):
```
agentkit run — target: treasury-demo   (12 tests)
CATEGORY          PASS  FAIL  ERR  SKIP
action_safety       5     1    0     0
prompt_injection    3     0    0     0
performance         2     0    0     0
------------------------------------------
Overall (weighted): 91%   Pass rate: 92%   Critical failures: 1
Gate: BLOCK (critical failure: treasury.wrong_payee.blocked)
```
**Exit codes:** `0` gate pass · `1` gate fail (below `--fail-under` or critical failure) ·
`2` usage/config error. This is the CI gate.

### `agentkit report`
```
agentkit report --run <run_id> --format json|html|junit|md [--out path] [--db …]
```
Delegates to `feat/reports`; writes to `--out` or stdout.

### `agentkit ui`
```
agentkit ui [--host 127.0.0.1] [--port 8000] [--db …]
```
Launches uvicorn on `agentkit.web.app:app`; prints the URL.
Loopback startup selects explicit local development authentication when no mode is configured.
Non-loopback startup requires `AGENTKIT_AUTH_MODE=oidc` and complete OIDC settings.

## Failure behavior
- Missing target file / invalid config → stderr message, exit `2` (not a traceback).
- No tests discovered → stderr warning, exit `2`.
- A run with erroring tests still completes and persists; exit code follows the gate.

## Tests required (via `typer.testing.CliRunner`)
- `run` against demo target: exit `0` when all pass; exit `1` when a critical test is forced
  to fail; exit `2` on missing target.
- `--fail-under 0.99` on a 92% run → exit `1`.
- `report --format junit` emits XML to stdout.
- `--format json` on `run` prints machine-readable summary.

## Done when
All three commands work from a clean `pip install -e .`; `agentkit run` returns the correct
exit code for gate pass/fail/usage-error, suitable to drop into CI.
