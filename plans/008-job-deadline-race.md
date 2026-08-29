# Plan 008: Stop labelling fully-completed jobs `expired`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**:
> `git diff --stat 5959852..HEAD -- backend/agentaudit/worker.py tests/test_worker.py`
> If either changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (independent of 006/007, but run after 006 so the suite
  is green and a new failure is unambiguously yours)
- **Category**: bug
- **Planned at**: commit `5959852`, 2026-08-29

## Why this matters

A job carries an optional `timeout_seconds` budget. The worker enforces it
cooperatively: `should_stop()` is polled by the runner *between tests*, and the
loop breaks when it returns True.

The bug is in what happens after the loop. `execute_job` calls `should_stop()`
a **second time**, after `execute_audit` has already returned, and treats a
True answer as proof the audit was cut short. But `should_stop()` re-reads the
clock. If the deadline elapses in the gap between the final test finishing and
that post-loop call, a job that executed **every one of its tests** is released
in state `expired` with the error `exceeded its time limit`.

The consequence is corrupted evidence metadata: a complete audit is filed as a
truncated one. Anything reading job state to decide whether a run is
trustworthy — the dashboard, a release gate, a compliance export — is told the
evidence is partial when it is complete. The run rows themselves are fine,
which makes the discrepancy harder to notice, not easier.

The window is small but it is widest exactly where it hurts: a job that uses
almost all of its budget is the most likely to cross the deadline during the
final save, and is also the job most likely to be near a real timeout.

## Current state

- `backend/agentaudit/worker.py` — the job worker. `execute_job` builds the
  stop predicate and interprets the audit's outcome.
- `backend/agentaudit/core/runner.py` — polls the predicate; not modified here.
- `tests/test_worker.py` — worker tests, including the two existing budget
  tests you will model the new one on.

Excerpt (`backend/agentaudit/worker.py:254-286`, verified at `5959852`):

```python
    deadline = time.monotonic() + job.timeout_seconds if job.timeout_seconds else None

    def should_stop() -> bool:
        if deadline is not None and time.monotonic() >= deadline:
            return True
        return store.jobs.is_cancelled(job.id)

    # The egress decision above binds every request the audit makes, discovery
    # probes included. `external` stays off for exactly that reason: a spawned
    # scanner re-resolves the hostname itself, so the pinned address would not
    # bind it, and this worker runs partner endpoints.
    audit = execute_audit(
        target,
        tests,
        redactor=redactor,
        endpoint=endpoint,
        plan=True,
        on_plan=count,
        on_result=note,
        should_stop=should_stop,
    )
    if should_stop():
        # A stop after some tests finished still saves what ran as a (shorter)
        # run -- partial evidence is evidence. Before the first test there is
        # nothing to keep, so the job ends without a run. Cancel wins the label
        # when both fired.
        error = CANCELLED_ERROR if store.jobs.is_cancelled(job.id) else TIMEOUT_ERROR
        result, report = audit.result, audit.report
        run_id: str | None = None
        if result.results:
            store.save_run(job.org_id, target, result, report, job.created_by, plan=audit.plan)
            run_id = result.run_id
        raise JobCancelled(job.id, run_id, error=error)
```

Line 275 (`if should_stop():`) is the defect: it *asks again* instead of
recording what happened.

The consumer side of the predicate (`backend/agentaudit/core/runner.py:462-464`,
for context only — **do not modify**):

```python
        for index, test in enumerate(tests):
            if should_stop is not None and should_stop():
                break
```

The poll happens at the top of each iteration. When every test runs, the loop
exhausts normally and the predicate is never asked again — which is precisely
why the worker must remember the answer rather than recompute it.

### Repo conventions

100-char lines, ruff `E`/`F`/`I`/`B`/`UP`, four-space indent, type annotations
on signatures. Comments explain *why*. `time` is already imported in
`worker.py`; add no new imports.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Worker tests | `python -m pytest tests/test_worker.py -q` | all pass |
| One test | `python -m pytest tests/test_worker.py -k <name>` | passes |
| Full suite | `python -m pytest` | exit 0, `956 passed` (955 + your new test) |
| Lint | `python -m ruff check .` | `All checks passed!` |

**Windows note**: call pytest as a module (`python -m pytest`), never the
`uv run ... pytest` console script.

## Scope

**In scope** (the only files you should modify):
- `backend/agentaudit/worker.py`
- `tests/test_worker.py`

**Out of scope** (do NOT touch, even though they look related):
- `backend/agentaudit/core/runner.py` — the polling loop is correct. Do not add
  a "stopped" field to the runner or to `AuditRun`; that is a cross-module
  contract change and this bug does not need one.
- `backend/agentaudit/core/audit.py` / the `AuditRun` dataclass — same reason.
- `work_once` and the `JobCancelled` handling at `worker.py:316-346` — the
  release-state mapping is correct; only the signal reaching it is wrong.
- `store.py`'s `timeout_seconds` validation and schema — correct as-is.

## Git workflow

- Branch: `fix/008-job-deadline-race` (already created off `develop`).
- Suggested commit: `fix(jobs): only expire a job the audit actually stopped for`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Make the stop decision sticky

In `backend/agentaudit/worker.py`, introduce a flag that records whether the
predicate ever answered True, and have the predicate set it. Replace the
`deadline` / `should_stop` block (lines 254-259) with:

```python
    deadline = time.monotonic() + job.timeout_seconds if job.timeout_seconds else None
    # Sticky, because the post-audit check below must reflect the answer the
    # runner acted on -- not a fresh clock reading. Re-asking would label a job
    # that ran every test `expired` whenever the deadline lands in the gap
    # between the last test and this check.
    stopped = False

    def should_stop() -> bool:
        nonlocal stopped
        if deadline is not None and time.monotonic() >= deadline:
            stopped = True
        elif store.jobs.is_cancelled(job.id):
            stopped = True
        return stopped
```

Then change line 275 from `if should_stop():` to:

```python
    if stopped:
```

Leave the body of that branch — including the
`error = CANCELLED_ERROR if store.jobs.is_cancelled(job.id) else TIMEOUT_ERROR`
line — exactly as it is. Cancel must still win the label when both fired, and
that line is what makes it do so.

**Verify**:
```
python -m pytest tests/test_worker.py -q
python -m ruff check .
```
→ all existing worker tests still pass (including
`test_a_job_past_its_time_limit_expires_and_keeps_partial_evidence`,
`test_a_job_inside_its_time_limit_finishes_normally`, and
`test_a_cancel_beats_a_timeout_when_both_fired`); ruff clean.

If `test_a_cancel_beats_a_timeout_when_both_fired` fails, STOP — the sticky
flag has changed the cancel-vs-timeout precedence and the fix needs rethinking.

### Step 2: Add a regression test for the race

Add one test to `tests/test_worker.py`, placed immediately after
`test_a_job_inside_its_time_limit_finishes_normally`.

Model it structurally on
`test_a_job_past_its_time_limit_expires_and_keeps_partial_evidence`
(`tests/test_worker.py:562-591`), which already demonstrates the technique:
monkeypatch `JobQueue.record_progress` to jump `time.monotonic` past the budget
instead of sleeping through a real timeout.

The difference: that test exhausts the budget after the **first** of two tests,
so the audit is genuinely cut short. Yours must exhaust it after the **last**
test, so every test ran and only the post-loop check sees an elapsed deadline.

Shape:

```python
def test_a_job_that_ran_every_test_is_done_even_if_the_budget_lapses_after(
    tmp_path, monkeypatch
):
    """The deadline landing between the final test and the post-audit check is
    not a timeout: every test ran, so the evidence is complete and the job is
    `done`, not `expired`."""
    store = Store(str(tmp_path / "late-lapse.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    tests = [{**_TEST, "id": f"w.pass.case.{n}"} for n in range(2)]
    store.save_pack("org-a", "pack-1", "Pack One", tests)
    job_id = store.jobs.enqueue("org-a", "worker-target", "pack-1", timeout_seconds=60)

    # Exhaust the budget only once the LAST test has been recorded, so the
    # runner's between-tests poll never sees it and the loop runs to completion.
    original_record_progress = JobQueue.record_progress
    clock = time.monotonic()
    seen = []

    def _record_then_lapse_after_last(self, job_id_, test_id, status):
        original_record_progress(self, job_id_, test_id, status)
        seen.append(test_id)
        if len(seen) == len(tests):
            monkeypatch.setattr(time, "monotonic", lambda: clock + 3600)

    monkeypatch.setattr(JobQueue, "record_progress", _record_then_lapse_after_last)

    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "done"
    assert job.error is None
    assert job.run_id is not None

    run, _ = store.get_run("org-a", job.run_id)
    assert [r.test_id for r in run.results] == ["w.pass.case.0", "w.pass.case.1"]
```

Use the imports and fixtures already present at the top of `tests/test_worker.py`
(`Store`, `JobQueue`, `work_once`, `_TARGET_CONFIG`, `_TEST`, `time`,
`monkeypatch`). Add no new imports unless one is genuinely missing.

**Verify**: first confirm the test actually catches the bug. Temporarily revert
step 1 (change `if stopped:` back to `if should_stop():`) and run:
```
python -m pytest tests/test_worker.py -k late_lapse_or_your_test_name -q
```
→ **fails** with `assert 'expired' == 'done'`.

Then re-apply step 1 and run it again → **passes**. A regression test that
passes against the unfixed code proves nothing; do not skip this check.

### Step 3: Full verification

```
python -m pytest -q
python -m ruff check .
```

**Verify**: `956 passed`, 0 failed; ruff `All checks passed!`.

(If plan 006 has not landed, you will see its 4 failures here as well. That is
expected and not caused by this plan — but confirm they are exactly those four
and no others.)

## Test plan

- **New test**: one, in `tests/test_worker.py`, per step 2 — the deadline
  lapsing after the final test must yield `done`, not `expired`, with all
  results persisted.
- **Structural pattern**: `test_a_job_past_its_time_limit_expires_and_keeps_partial_evidence`
  (`tests/test_worker.py:562`).
- **Existing tests that must keep passing** (they are the guard against
  over-correcting — a fix that makes timeouts stop working would pass your new
  test but fail these):
  - `test_a_job_past_its_time_limit_expires_and_keeps_partial_evidence`
  - `test_a_job_inside_its_time_limit_finishes_normally`
  - `test_a_cancel_beats_a_timeout_when_both_fired`
- **Verification**: `python -m pytest tests/test_worker.py -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest tests/test_worker.py -q` exits 0, all pass
- [ ] `python -m pytest` reports `956 passed` (or 955 + 1 new, with plan 006's
      four failures if 006 has not yet landed — and no others)
- [ ] `python -m ruff check .` exits 0
- [ ] `grep -n "if stopped:" backend/agentaudit/worker.py` returns exactly one match
- [ ] `grep -c "if should_stop():" backend/agentaudit/worker.py` returns `0`
- [ ] `grep -n "nonlocal stopped" backend/agentaudit/worker.py` returns one match
- [ ] The new test fails against the unfixed code (demonstrated in step 2)
- [ ] `git status --short` shows exactly two modified files and no others
- [ ] `plans/README.md` status row for 008 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- `test_a_cancel_beats_a_timeout_when_both_fired` fails after step 1 — the
  sticky flag has altered cancel-vs-timeout precedence.
- `test_a_job_past_its_time_limit_expires_and_keeps_partial_evidence` fails —
  the fix has broken genuine timeout detection, which is worse than the bug.
- Your new test passes *before* step 1 is applied — it is not exercising the
  race, and needs restructuring before it is worth keeping.
- The code at `worker.py:254-286` does not match the "Current state" excerpt.
- You find yourself wanting to add a `stopped` field to `AuditRun` or change
  `runner.py` — that is out of scope; report instead.

## Maintenance notes

- **The invariant**: `stopped` must mean "the runner broke out of its loop",
  never "the clock says we are past the deadline now". Any future edit that
  recomputes the condition at the post-audit check reintroduces this bug.
- `should_stop` is now stateful. It is still safe to call repeatedly and from
  the runner's loop (single-threaded polling, one closure per job), but a future
  change that calls it from more than one thread would need a lock. Worth a
  reviewer's attention if the runner ever parallelizes tests.
- The same "ask again instead of remember" shape is what prior audit finding #4
  flagged in `work_once`; that one has since been handled at
  `worker.py:341-346`. If a third instance appears, the pattern is worth
  extracting rather than fixing individually.
- Reviewer should scrutinize: that the `error = CANCELLED_ERROR if ... else
  TIMEOUT_ERROR` line is unchanged, and that the new test genuinely fails
  against the old code.
