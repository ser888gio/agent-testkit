# Plan 017: Stop relabelling a fully-completed run as cancelled

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7cb6196..HEAD -- backend/agentaudit/worker.py tests/test_worker.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `7cb6196`, 2026-09-04

## Why this matters

A cancel request that arrives after the last test has finished, but before
`work_once` records the job's terminal state, turns a **complete** run into a
job labelled `failed` with the error text "cancelled by user".

The run itself is complete and fully persisted: every planned test produced a
result and `save_run` wrote them all. But the job row says the work failed and
was cancelled, so the operator sees complete evidence presented as partial. For
a tool whose output is compliance evidence, evidence that reports itself as
partial when it is complete is the exact inverse of the fail-closed property the
rest of the system is careful about.

This is the same class of bug as the already-merged plan 008, which stopped
fully-completed jobs being labelled `expired` when a deadline landed in the gap
after the last test. That fix introduced a **sticky `stopped` flag** — set only
when `should_stop()` actually caused the runner to stop — precisely so the
terminal check reflects the answer the runner acted on rather than a fresh clock
reading. The comment explaining it is eight lines above the code this plan
fixes. The cancel branch was simply never converted to use it.

`JobQueue.request_cancel`'s own docstring already says a running job "only gets
the flag set: the worker checks it between tests and releases the job itself".
A cancel that arrives after the last test lost that race. Recording the job as
`done` is what that contract already promises.

## Current state

Files involved:

- `backend/agentaudit/worker.py` — contains both the sticky flag (correct) and
  the stale re-read (the bug). This is the file you change.
- `tests/test_worker.py` — where the regression test goes.
- `backend/agentaudit/core/store.py` — read-only. Defines
  `CANCELLED_ERROR = "cancelled by user"` at line 263 and `JobQueue.release`.

`backend/agentaudit/worker.py:391-406` — the sticky flag, already correct. Note
the comment; it is the reasoning this plan extends to the cancel case:

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
        elif lost_lease is not None and lost_lease.is_set():
            stopped = True
        elif store.jobs.is_cancelled(job.id):
            stopped = True
        return stopped
```

`backend/agentaudit/worker.py:426-437` — the partial-run path, already correct.
When `stopped` is true, a `JobCancelled` is raised and the job is labelled by
`work_once`'s `except` branch. **Do not change this.**

```python
    if stopped:
        # A stop after some tests finished still saves what ran as a (shorter)
        # run -- partial evidence is evidence. Before the first test there is
        # nothing to keep, so the job ends without a run. Cancel wins the label
        # when both fired.
        error = CANCELLED_ERROR if store.jobs.is_cancelled(job.id) else TIMEOUT_ERROR
        ...
        raise JobCancelled(job.id, run_id, error=error)
```

`backend/agentaudit/worker.py:499-503` — **the bug**. This is the `else:` branch
of `work_once`'s `try`, i.e. the path taken only when `execute_job` returned
normally, which by definition means `stopped` was false and every planned test
ran:

```python
    else:
        if store.jobs.is_cancelled(job.id):
            store.jobs.release(job.id, owner, state="failed", run_id=run_id, error=CANCELLED_ERROR)
        else:
            store.jobs.release(job.id, owner, state="done", run_id=run_id)
```

`backend/agentaudit/core/store.py` — `JobQueue.request_cancel`'s docstring, the
contract this plan honors:

> A queued job has no worker to interrupt, so it goes straight to 'cancelled'. A
> running job only gets the flag set: the worker checks it between tests (see
> `is_cancelled`) and releases the job itself, the same way any other terminal
> transition happens under its own lease.

Repo conventions:

- Comments explain *why*, in full sentences. `worker.py:392-396` is the model.
- Tests are flat `def test_<behavior>(tmp_path, monkeypatch)` functions.
  `tests/test_worker.py:152-178` is the closest structural exemplar — it
  monkeypatches `JobQueue.record_progress` to inject a cancel at a precise point
  in the run. Read it before writing yours.
- Line length 100; ruff selects `E, F, I, B, UP`, currently green.

## Commands you will need

| Purpose        | Command                                                              | Expected on success     |
|----------------|----------------------------------------------------------------------|-------------------------|
| Worker tests   | `python -m pytest tests/test_worker.py`                               | all pass                |
| One test       | `python -m pytest tests/test_worker.py -k cancel`                     | all pass                |
| Web tests      | `python -m pytest tests/test_web.py`                                  | all pass                |
| Lint           | `python -m ruff check .`                                              | `All checks passed!`    |
| Full suite     | `python -m pytest`                                                    | `1066 passed` (or more) |

**Windows note**: call pytest and ruff as modules (`python -m pytest`), never as
console scripts.

## Scope

**In scope** (the only files you should modify):

- `backend/agentaudit/worker.py` — the `else:` branch of `work_once` only
  (around lines 499-503)
- `tests/test_worker.py` — add one regression test

**Out of scope** (do NOT touch, even though they look related):

- `should_stop` and the `stopped` flag (`worker.py:391-406`) — already correct.
- The `if stopped:` block (`worker.py:426-437`) — the partial-evidence path is
  correct and its `failed` + `CANCELLED_ERROR` labelling is intended. A genuine
  mid-run cancel **must keep** producing `state == "failed"`, `error ==
  "cancelled by user"`, and a linked partial run. `tests/test_worker.py:152`
  asserts exactly that and must keep passing unchanged.
- The `except JobCancelled` branch (`worker.py:477-486`) — unchanged.
- `backend/agentaudit/core/store.py` — `request_cancel`, `is_cancelled` and
  `release` all behave correctly. Do not change their semantics.
- `JobQueue.is_cancel_requested` — a redundant alias for `is_cancelled`. It is
  dead code and worth deleting one day, but not in this plan.

## Git workflow

- Branch off `develop`: `git checkout -b fix/017-completed-run-is-not-cancelled develop`
- Conventional-commit subject, e.g.
  `fix: keep a fully-completed run's job done when a late cancel arrives`
- Commit message must end with:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Release a completed job as `done`

In `backend/agentaudit/worker.py`, replace the `else:` branch of `work_once`'s
`try` so it always releases `done`:

```python
    else:
        # Reached only when `execute_job` returned normally, which means
        # `should_stop` never fired and every planned test produced a result.
        # A cancel flag that appears now arrived after the last test and lost
        # the race that `request_cancel` documents -- the worker checks between
        # tests. Re-reading it here would label complete evidence partial, the
        # same mistake the sticky `stopped` flag above exists to prevent.
        store.jobs.release(job.id, owner, state="done", run_id=run_id)
```

Keep the comment; it is the reason this line will not be "helpfully" reverted
later. Match the wording style of `worker.py:392-396`.

Confirm `CANCELLED_ERROR` is still used elsewhere in the file before assuming
its import is now unused — it is used at `worker.py:81` and `worker.py:431`, so
the import must **stay**. If ruff reports `F401` after your edit, you removed
too much.

**Verify**:

- `python -m pytest tests/test_worker.py` → all pass, **including** the
  existing `test_cancel_requested_mid_run_stops_the_job_and_keeps_partial_evidence`,
  which must still see `state == "failed"`.
- `grep -n "is_cancelled" backend/agentaudit/worker.py` → matches only inside
  `should_stop` (around line 404) and the `if stopped:` block (around line 431).
  No match in the `else:` branch.

### Step 2: Add the regression test

Add a test to `tests/test_worker.py` proving that a cancel arriving **after the
last test** leaves the job `done` with the complete run attached.

The mechanic: model it on `tests/test_worker.py:152-178`, but instead of
cancelling after the *first* test's progress, cancel after the *last* one. With
a two-test pack, monkeypatch `JobQueue.record_progress` to call
`request_cancel` only once both tests have recorded — count the calls in a
closure.

Assert all four:

- `job.state == "done"`
- `job.error is None`
- `job.run_id is not None`
- the linked run contains **both** test ids, i.e. nothing was truncated

Read the existing test's setup helpers (`_TARGET_CONFIG`, `_TEST`,
`store.save_pack`, `work_once`) and reuse them rather than building new ones.

**Verify**: `python -m pytest tests/test_worker.py -k cancel` → all pass,
including your new test and the three existing cancel tests.

### Step 3: Full validation

**Verify**:

- `python -m ruff check .` → `All checks passed!`
- `python -m pytest` → `1066 passed` or more, `0 failed`

## Test plan

- **New test in `tests/test_worker.py`**: a cancel that lands after the final
  test's progress leaves the job `done`, with no error text and a complete run.
- **Existing tests that must keep passing unchanged** — these pin the behavior
  this plan must *not* alter:
  - `test_cancel_requested_mid_run_stops_the_job_and_keeps_partial_evidence`
    (`tests/test_worker.py:152`) — mid-run cancel still yields `failed` +
    `"cancelled by user"` + a partial run.
  - `test_cancel_requested_before_the_run_starts_stops_it_before_the_first_test`
    (`tests/test_worker.py:223`).
  - `test_work_once_releases_a_cancelled_job_without_a_run`
    (`tests/test_worker.py:244`) — yields `cancelled` with no run.
- **Structural pattern**: `tests/test_worker.py:152-178`.
- **Verification**: `python -m pytest tests/test_worker.py` → all pass,
  including 1 new test.

## Done criteria

ALL must hold:

- [ ] `python -m ruff check .` exits 0 with `All checks passed!`
- [ ] `python -m pytest` exits 0 with at least `1066 passed`, `0 failed`
- [ ] `grep -n "is_cancelled" backend/agentaudit/worker.py` shows no match
      inside `work_once`'s `else:` branch
- [ ] 1 new test in `tests/test_worker.py` asserts `state == "done"` for a
      post-last-test cancel
- [ ] The three existing cancel tests pass **unmodified** (`git diff` shows no
      change to them)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/README.md` status row for 017 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts in "Current state" do not match the live code.
- You need to modify any existing cancel test to make the suite pass. That would
  mean this change altered mid-run cancel behavior, which it must not. Report
  which test and why.
- The new test cannot be made to fail against the *unfixed* code. Verify this:
  write the test first, run it on the current `worker.py`, and confirm it fails
  with `state == "failed"`. If it passes before your fix, the test is not
  reproducing the bug and needs a different injection point.
- Making the `else:` branch correct appears to require changing
  `JobQueue.release` or `request_cancel`.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- The invariant, now consistent across both stop reasons: **a terminal-state
  decision must use the sticky `stopped` flag, never a fresh read of the
  cancel/deadline source.** Deadline was fixed by plan 008; cancel is fixed
  here. If a third stop reason is ever added to `should_stop`, it inherits the
  same rule and must not grow its own post-run re-read.
- A reviewer should check that the `if stopped:` block is untouched. It is
  legitimately allowed to re-read `is_cancelled` — at that point the flag has
  already fired and the re-read only picks *which* label a genuinely-stopped run
  gets. That is a different question from *whether* it stopped.
- Behavior change visible to users: a job that was cancelled a moment too late
  now reports `done` instead of `failed`. That is correct — the run is complete
  — but a UI that says "cancelled" based on the user's click rather than the job
  state may now disagree with the job row. Worth a glance at the SPA's job
  status rendering if anyone reports confusion.
- Deferred out of this plan: `JobQueue.is_cancel_requested` (`store.py:631`) is
  a one-line alias for `is_cancelled` with no production caller. Two names for
  one behavior in a cancellation path is genuinely confusing, but deleting it
  belongs with the other dead-`Store`-method cleanup, not here.
