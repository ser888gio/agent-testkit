# IMPROVE-CODE.md

Task list from the `/improve` audit (commit `78c0e2d`). Do them in order —
task 1 unblocks the test gate everything else relies on. After each task,
`python -m pytest -q` must exit 0.

Gate command (whole repo): `python -m pytest -q`

---

## 1. Fix the test suite so it collects (F1) — P1, do first

**Problem:** `examples/` was deleted (commit `ff8b7db`) but two test files still
import it, so `pytest` errors at collection and runs **nothing**:
- `tests/test_http_agent.py:7-8` — `from examples.demo_agent import create_agent` /
  `from examples.stub_endpoint import app as stub_app`
- `tests/test_examples.py` — `runpy.run_path("examples/run_*.py", ...)`

**Do:**

1. Delete `tests/test_examples.py` entirely. It only guarded the deleted example
   scripts (`examples/run_treasury.py`, `examples/run_email.py`); there is nothing
   left to smoke-test.
2. Rewrite `tests/test_http_agent.py` to depend on in-repo code only. Replace the
   two `examples.*` imports with:
   - callable agent: `from agentaudit.packs.core._demo_safe_agent import create_agent`
   - HTTP stub: build a tiny FastAPI app **in the test file** that mirrors
     `agentaudit/config/demo-stub-http.yaml` (`POST /run`, body `{"input": "..."}`,
     returns `{"text": "..."}`), wrapping the same `_safe_reply` so the parity
     assertion holds. Return HTTP 400 when the `input` key is absent (the second
     test asserts `r.error == "http 400"`).

   Target shape:
   ```python
   from fastapi import FastAPI, HTTPException
   from fastapi.testclient import TestClient
   from agentaudit.packs.core._demo_safe_agent import create_agent, _safe_reply

   stub_app = FastAPI()

   @stub_app.post("/run")
   def _run(body: dict):
       if "input" not in body:
           raise HTTPException(status_code=400, detail="missing input")
       return {"text": _safe_reply(body["input"])}
   ```
   Keep the existing `_stub_request_fn`, `http_agent` fixture, and both test bodies
   unchanged — they already reference `stub_app` / `create_agent`.

**Verify:** `python -m pytest -q` → exits 0, ~147 tests pass, **0 collection errors**.

**STOP if:** the parity test `test_http_and_callable_agent_produce_identical_text`
fails — it means the callable and the stub don't share `_safe_reply`; re-check both
use the same function, don't invent new reply logic.

---

## 2. Redact numeric scalars (F2) — P1

**Problem:** `agentaudit/core/redaction.py:74-81` — `Redactor.redact()` recurses into
`dict`/`list` and redacts `str`, but returns `copy.deepcopy(value)` for every other
scalar. A numeric account/card/phone in an agent's JSON response
(e.g. `{"account_number": 123456789}`) is stored **verbatim** in `agentaudit.db` and
shown in the dashboard — breaking the "redaction by default" guarantee.

**Do:** in `Redactor.redact`, handle `int`/`float` by running text redaction on their
string form. Guard `bool` first (`isinstance(True, int)` is `True` — don't touch it):

```python
def redact(self, value: Any) -> Any:
    if isinstance(value, str):
        return self.redact_text(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        masked = self.redact_text(str(value))
        return masked if masked != str(value) else value  # only change if it matched
    if isinstance(value, dict):
        return {k: self.redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [self.redact(v) for v in value]
    return copy.deepcopy(value)
```

A matched number becomes a mask string (type changes int→str); evidence is JSON, so
that's fine. Unmatched numbers keep their original type/value.

**Test:** add to `tests/test_redaction.py`, following the existing test style:
- `{"account_number": 123456789}` → value becomes a mask (matched by the `account`
  builtin `\b\d{8,17}\b`).
- `{"amount": 42}` and `{"ok": True}` → unchanged (short int; bool untouched).

**Verify:** `python -m pytest -q tests/test_redaction.py` → all pass, new cases green.

---

## 3. Redact evidence once, not twice (F3) — P2

**Problem:** the runner already redacts evidence into `TestResult`
(`agentaudit/core/runner.py:105-107` via `_redact_evidence`), then `Store.save_run`
redacts the **same** payload a second time (`agentaudit/core/store.py:88, 122-131`),
re-instantiating a `Redactor` from the same config. Redundant work, and no single
source of truth.

**Do:** make the runner the sole redaction point; the store trusts what it's given.
In `Store.save_run`:
- Delete the `redactor = Redactor(agent.evidence.redact)` line.
- Replace the `redactor.redact(payload["request"])` / `["response"]` block with the
  serialized values as-is (they're already redacted, and already `None` when
  `store_request` / `store_response` is off — the runner handles that). Drop the now
  unused `Redactor` import if nothing else uses it.

**STOP if:** any test in `tests/test_store.py` feeds `save_run` a hand-built
un-redacted `TestResult` and asserts the store redacts it. If so, that test encodes
the old contract — update it to build evidence the way the runner does (pre-redacted)
rather than reintroducing redaction in the store.

**Verify:** `python -m pytest -q` → exits 0 (esp. `tests/test_store.py`,
`tests/test_runner.py`).

---

## 4. Add a ruff lint + format gate (F4) — P2

**Problem:** `.ruff_cache/` exists but `pyproject.toml` has no ruff config, so there's
no style/lint gate. Add one so future changes have a machine check.

**Do:**
1. Add ruff to dev deps in `pyproject.toml`:
   ```toml
   [project.optional-dependencies]
   dev = ["pytest", "ruff"]
   ```
2. Add config to `pyproject.toml`:
   ```toml
   [tool.ruff]
   line-length = 100
   target-version = "py310"

   [tool.ruff.lint]
   select = ["E", "F", "I", "B", "UP"]
   ```
3. Run `ruff check .` and fix real findings (unused imports, etc.). Run
   `ruff format .` only if the diff is small and mechanical; otherwise leave
   formatting and just satisfy `ruff check`.

**STOP if:** `ruff check .` reports a large number of pre-existing violations
(>~30). Don't mass-rewrite the repo — narrow `select` to `["F", "I"]` (unused/undefined
names + import order), fix those, and note the rest as follow-up.

**Verify:** `ruff check .` → exits 0; `python -m pytest -q` → still exits 0.

---

## 5. Stop leaking worker threads on timeout (F5) — P3

**Problem:** `agentaudit/core/runner.py:30-40` — `_run_with_timeout` creates a new
`ThreadPoolExecutor` per test and, on timeout, calls `shutdown(wait=False)`; the hung
`agent.run` thread keeps running for the process lifetime. Against a slow/flaky HTTP
endpoint, threads and sockets accumulate.

**Do (lazy, honest):** Python can't force-kill a thread, so make the leak bounded and
loud rather than pretending to cancel:
- Use daemon threads so they never block process exit: pass
  `ThreadPoolExecutor(max_workers=1, thread_name_prefix="agentaudit-agent")` and rely on
  the interpreter reaping daemons at exit (thread-pool workers are daemonic by default
  in CPython, so the process-exit hang is already avoided — verify).
- Add a `ponytail:` comment stating the ceiling:
  `# ponytail: a timed-out agent.run thread runs to completion (no thread kill in`
  `# Python); HTTPAgent's own timeout_s bounds the common case. Revisit with`
  `# cooperative cancellation if long-hanging callables become real.`

Do **not** build a subprocess/cancellation framework for this — not worth it for a
test tool.

**Verify:** `python -m pytest -q tests/test_runner.py` → exits 0 (timeout test still
returns `error="timeout"`).

---

## 6. Constrain web run/compare paths (F6) — P3, defensive

**Problem:** `agentaudit/web/app.py:230-238` — `POST /runs?target=&packs=` loads any YAML
path and `discover()` will `exec_module` any `test_*.py` under the given dir
(`agentaudit/core/loader.py:113-122`). `agentaudit ui` defaults to `127.0.0.1` (safe), but
if it's ever bound to `0.0.0.0` (`--host`), these routes are arbitrary-file-read / RCE.

**Do:** reject `target`/`packs` that resolve outside the current working directory, in
`run_again`. Add a small helper:

```python
def _safe_path(p: str) -> Path:
    resolved = Path(p).resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise HTTPException(status_code=400, detail="path escapes project root")
    return resolved
```

Use it for `target` and `packs` before `load_target` / `discover`. `compare_runs` takes
run ids (not filesystem paths), so it needs no change. Also add one line to the
README / `agentaudit ui` help noting that `--host 0.0.0.0` exposes run-triggering and
should stay off untrusted networks.

**STOP if:** existing tests pass relative paths that legitimately live outside cwd —
then relax the guard to an explicit allow-root env var rather than blocking.

**Verify:** `python -m pytest -q tests/test_web.py` → exits 0; a manual
`POST /runs?target=../../etc/x.yaml` returns 400.

---

## Done criteria (all tasks)

- [ ] `python -m pytest -q` exits 0 with no collection errors
- [ ] `ruff check .` exits 0 (task 4)
- [ ] `grep -rn "examples" tests/` returns nothing (task 1)
- [ ] New redaction tests for numeric scalars exist and pass (task 2)
