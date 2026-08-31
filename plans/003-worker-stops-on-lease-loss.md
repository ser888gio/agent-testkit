# Plan 003: Stop the worker when its job lease is lost

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.

> **Drift check (run first)**:
> `git diff --stat 89a3068..HEAD -- backend/agentaudit/worker.py tests/test_worker.py`
> If either changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (plan 008, which rewrote the same function, is already
  merged — this plan is written against the post-008 code)
- **Category**: bug
- **Planned at**: commit `89a3068`, 2026-08-29
- **Supersedes**: the 2026-08-26 version of this plan, written at `e4cfe48`.
  That version's excerpts predated both the `timeout_seconds` feature
  (`ce5c452`) and plan 008, and its Step 2 would have reverted 008's fix.

## Why this matters

A worker holds a job by heartbeating a lease. `_heartbeat` runs on a daemon
thread; when `store.jobs.heartbeat(...)` returns False the lease is gone — the
job has been reclaimed and **another worker now owns it and is running it**.
Today `_heartbeat` logs a warning and returns, and nothing else happens: the
losing worker keeps auditing to completion.

Two concrete harms:

1. **Duplicate live traffic.** This is a black-box agent auditor. Two workers
   running the same job means the partner's endpoint is dialled twice, and
   attack packs are fired at it twice. That is real traffic against someone
   else's production system.
2. **Duplicate/garbage evidence.** The losing worker finishes and tries to
   persist a run for a job it no longer owns.

The stop plumbing already exists — `should_stop` is polled between tests. Only
the wiring from heartbeat failure to that plumbing is missing.

## Current state

- `backend/agentaudit/worker.py` — the worker.
- `tests/test_worker.py` — worker tests.

`_heartbeat` (`worker.py:81-87`, verified at `89a3068`):

```python
def _heartbeat(store: Store, job_id: str, owner: str, stop: threading.Event, lease: int) -> None:
    # Extend well inside the lease so one slow beat does not lose the job.
    interval = max(lease / 4, 1.0)
    while not stop.wait(interval):
        if not store.jobs.heartbeat(job_id, owner, lease_seconds=lease):
            log.warning("job %s: lease lost, another worker owns it now", job_id)
            return
```

The stop predicate in `execute_job` (`worker.py:254-267`) — **note this is the
post-008 sticky form; do not revert it**:

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

The post-audit branch (`worker.py:287-296`):

```python
    if stopped:
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

The heartbeat thread's construction in `work_once` (`worker.py:318-322`):

```python
    stop = threading.Event()
    beat = threading.Thread(
        target=_heartbeat, args=(store, job.id, owner, stop, lease_seconds), daemon=True
    )
    beat.start()
```

And `work_once`'s existing infrastructure-fault branch (`worker.py:341-347`),
which is the pattern this plan reuses — **a failure that deliberately does NOT
release the job**:

```python
    except Exception:
        # Infrastructure fault. Deliberately not released: the lease expires and
        # `reclaim_jobs` retries it, up to the attempt ceiling. Releasing it as
        # failed here would turn a transient database blip into a dead job.
        ...
        log.error("job %s hit an infrastructure fault; leaving it to lease expiry", job.id)
```

### The design decision this plan makes (read before coding)

Lease loss is **not** a cancel and **not** a timeout, and it must not be routed
into the `if stopped:` branch above. Two reasons:

1. That branch calls `store.save_run(...)` when any test finished. For lease
   loss that persists the *losing* worker's partial run — which is exactly the
   duplicate-evidence harm this plan exists to prevent.
2. Its error label is `CANCELLED_ERROR if is_cancelled else TIMEOUT_ERROR`. A
   lease loss is neither, so it would be mislabelled a timeout.

So lease loss gets its own exception and its own `work_once` branch that saves
nothing and releases nothing, letting the new owner proceed untouched. This
mirrors the infrastructure-fault branch quoted above.

### Repo conventions

100-char lines, ruff `E`/`F`/`I`/`B`/`UP`, four-space indent, type annotations
on signatures. Comments explain *why*. `threading`, `time` and `log` are
already imported in `worker.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Worker tests | `python -m pytest tests/test_worker.py -q` | all pass |
| One test | `python -m pytest tests/test_worker.py -k <name>` | passes |
| Full suite | `python -m pytest` | `960 passed, 1 skipped` (959 + your new test; 1 skip is the unbuilt SPA bundle) |
| Lint | `python -m ruff check .` | `All checks passed!` |

**Windows note**: call pytest as a module. `uv run ... pytest` fails here.

## Scope

**In scope**:
- `backend/agentaudit/worker.py`
- `tests/test_worker.py`

**Out of scope** (do NOT touch):
- The sticky `stopped` flag and the `if stopped:` branch semantics introduced
  by plan 008 — cancel and timeout behavior must be **byte-for-byte
  unchanged**. You are adding a third path beside them, not editing them.
- `backend/agentaudit/core/runner.py` and `core/audit.py`.
- `store.py`'s `heartbeat` / `release` / `reclaim` implementations.

## Git workflow

- Suggested commit: `fix(jobs): stop auditing when the job lease is lost`.
- Do NOT push or open a PR.

## Steps

### Step 1: Add a `LeaseLost` exception

In `backend/agentaudit/worker.py`, next to the existing `JobCancelled` class
(around line 59), add:

```python
class LeaseLost(Exception):
    """Raised when the heartbeat finds another worker has taken the job.

    Distinct from `JobCancelled` on purpose: the job is not cancelled, has not
    timed out, and is not ours to write to any more. Whoever reclaimed it is
    running it now, so this worker persists no run and releases no state --
    same discipline as the infrastructure-fault path in `work_once`.
    """

    def __init__(self, job_id: str):
        super().__init__(job_id)
        self.job_id = job_id
```

**Verify**: `python -m ruff check backend/agentaudit/worker.py` → exit 0

### Step 2: Let the heartbeat signal lease loss

Extend `_heartbeat` with a keyword-only parameter and set it on failure:

```python
def _heartbeat(
    store: Store,
    job_id: str,
    owner: str,
    stop: threading.Event,
    lease: int,
    *,
    lost: threading.Event | None = None,
) -> None:
    # Extend well inside the lease so one slow beat does not lose the job.
    interval = max(lease / 4, 1.0)
    while not stop.wait(interval):
        if not store.jobs.heartbeat(job_id, owner, lease_seconds=lease):
            log.warning("job %s: lease lost, another worker owns it now", job_id)
            if lost is not None:
                lost.set()
            return
```

Keep the default `None` so the signature stays backward compatible.

**Verify**: `python -m ruff check backend/agentaudit/worker.py` → exit 0

### Step 3: Observe lease loss in `execute_job`

Add an optional parameter to `execute_job`:
`lost_lease: threading.Event | None = None`.

Extend the sticky predicate with a lease-loss branch. **Add one `elif`; change
nothing else in this function:**

```python
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

Then, immediately **before** the existing `if stopped:` block, add the
lease-loss exit so it takes precedence and saves nothing:

```python
    if lost_lease is not None and lost_lease.is_set():
        # Another worker owns this job now. Persist nothing: its run would be a
        # duplicate evidence row for a job we no longer hold.
        raise LeaseLost(job.id)
    if stopped:
        ...unchanged...
```

**Verify**: `python -m pytest tests/test_worker.py -q` → all pass, unchanged.
Cancel and timeout behavior must be untouched. In particular these three must
still pass:
`test_a_job_past_its_time_limit_expires_and_keeps_partial_evidence`,
`test_a_job_inside_its_time_limit_finishes_normally`,
`test_a_cancel_beats_a_timeout_when_both_fired`,
plus `test_a_job_that_ran_every_test_is_done_even_if_the_budget_lapses_after`.

### Step 4: Wire it up in `work_once`

Create the event, pass it to both the thread and `execute_job`, and handle the
new exception:

```python
    stop = threading.Event()
    lost_lease = threading.Event()
    beat = threading.Thread(
        target=_heartbeat,
        args=(store, job.id, owner, stop, lease_seconds),
        kwargs={"lost": lost_lease},
        daemon=True,
    )
    beat.start()
    try:
        run_id = execute_job(store, job, lost_lease=lost_lease)
    except LeaseLost:
        # Deliberately not released and nothing saved: the reclaiming worker
        # owns this job now, and `release` is owner-guarded anyway. Writing here
        # would race the new owner's state.
        log.warning("job %s: stopped after losing the lease; leaving it to its new owner", job.id)
    except JobCancelled as exc:
        ...unchanged...
```

Place the `except LeaseLost:` clause **before** `except JobCancelled:`.

**Verify**: `python -m pytest tests/test_worker.py -q` → all pass

### Step 5: Add the regression test

In `tests/test_worker.py`, after the existing budget tests, add a test that
makes the heartbeat fail and asserts the worker stops without writing.

Model it on `test_a_job_past_its_time_limit_expires_and_keeps_partial_evidence`
for structure (real `Store`, monkeypatched `JobQueue` method, `work_once`).
The mechanism here is: monkeypatch `JobQueue.heartbeat` to return `False`, and
use `JobQueue.record_progress` as the hook that fires it after the first test —
the same trick the budget tests use to act mid-run.

Assert:
1. Fewer results were executed than the pack contains (it stopped early).
2. No run was persisted by this worker — `store.list_runs(...)` shows no run
   for this job (`job.run_id is None`).
3. The job was **not** released into a terminal state by this worker.

Name it `test_lease_loss_stops_execution_and_persists_nothing`.

Because `_heartbeat` only beats every `max(lease/4, 1.0)` seconds, do **not**
rely on the real heartbeat thread's timing. Set `lost_lease` through the
`record_progress` hook instead, or use a short `lease_seconds`, whichever the
existing tests' style supports. If you cannot make the timing deterministic
within the existing patterns, STOP and report rather than adding a `sleep`.

**Verify**: `python -m pytest tests/test_worker.py -k lease -q` → new test passes.

Then prove it catches the bug: temporarily revert Step 3's `raise LeaseLost`
line, re-run the new test, and confirm it **fails**. Restore, re-run, confirm it
passes. Report the observed output of both runs.

### Step 6: Full verification

```
python -m pytest -q
python -m ruff check .
```

**Verify**: `960 passed, 1 skipped`, 0 failed; ruff clean.

## Test plan

- **New test**: one, per Step 5.
- **Structural pattern**: `test_a_job_past_its_time_limit_expires_and_keeps_partial_evidence`.
- **Regression guards that must keep passing** (these prove you did not disturb
  plan 008's fix): the four budget/cancel tests named in Step 3.

## Done criteria

- [ ] `python -m pytest tests/test_worker.py -q` exits 0, all pass
- [ ] `python -m pytest` reports `960 passed, 1 skipped`, 0 failed
- [ ] `python -m ruff check .` exits 0
- [ ] `grep -c "class LeaseLost" backend/agentaudit/worker.py` returns `1`
- [ ] `grep -c "except LeaseLost:" backend/agentaudit/worker.py` returns `1`
- [ ] `grep -c "nonlocal stopped" backend/agentaudit/worker.py` returns `1`
      (008's sticky flag still intact)
- [ ] The new test fails against the un-raised `LeaseLost` (Step 5, output reported)
- [ ] `git status --short` shows exactly two modified files
- [ ] Commit created with the required trailers

## STOP conditions

Stop and report back if:

- Any of the four cancel/timeout/budget tests named in Step 3 fails — you have
  disturbed plan 008's merged fix, which is worse than this bug.
- `worker.py` does not match the "Current state" excerpts (in particular, if
  `should_stop` does **not** contain `nonlocal stopped`, you are on pre-008
  code and this plan does not apply — STOP immediately).
- You cannot make the lease-loss test deterministic without a `sleep`.
- The new test passes before Step 3's `raise LeaseLost` is added.
- You find yourself editing the `if stopped:` branch body or the
  `error = CANCELLED_ERROR if ... else TIMEOUT_ERROR` line.

## Maintenance notes

- Three distinct stop reasons now share one predicate: deadline, lease loss,
  and cancel. Only lease loss exits without writing. A fourth reason should ask
  the same question — is this job still ours to write to?
- `release` is owner-guarded, so the no-release choice in Step 4 is belt and
  braces rather than strictly required. It is still the right shape: relying on
  a downstream guard to make an incorrect call harmless is how the guard
  eventually gets removed by someone who thinks it is unused.
- Reviewer should scrutinize: that 008's sticky flag survived untouched, and
  that the lease-loss branch really persists nothing (no `save_run` reachable
  on that path).
