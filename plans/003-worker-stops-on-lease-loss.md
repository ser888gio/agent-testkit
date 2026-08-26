# Plan 003: Stop the worker when its job lease is lost

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat e4cfe48..HEAD -- backend/agentaudit/worker.py tests/test_worker.py`
> On any mismatch with "Current state" excerpts below, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (do BEFORE any future work on the cancel-vs-done race,
  which lives in the same function)
- **Category**: bug
- **Planned at**: commit `e4cfe48`, 2026-08-26

## Why this matters

A worker extends its job lease via heartbeats. When a heartbeat fails (GC
pause, network blip, machine sleep > lease window), another worker reclaims
and re-runs the job. Today the original worker merely *logs* the loss and
keeps auditing: both workers dial the partner agent endpoint concurrently
(doubled attack traffic against live third-party systems) and both persist
runs, interleaving progress counters and duplicating evidence rows. The
plumbing to stop already exists (`should_stop`, owner-guarded release); only
the wiring between heartbeat failure and that plumbing is missing.

## Current state

- `backend/agentaudit/worker.py` — the worker loop.
- `tests/test_worker.py` — 31 tests covering lease/cancel semantics; the
  place to add the new case.

Verified excerpts at commit `e4cfe48`:

Heartbeat thread gives up silently on lease loss (`worker.py:68-74`):

```python
def _heartbeat(store: Store, job_id: str, owner: str, stop: threading.Event, lease: int) -> None:
    # Extend well inside the lease so one slow beat does not lose the job.
    interval = max(lease / 4, 1.0)
    while not stop.wait(interval):
        if not store.jobs.heartbeat(job_id, owner, lease_seconds=lease):
            log.warning("job %s: lease lost, another worker owns it now", job_id)
            return
```

Thread creation and event wiring (`worker.py:291-295`):

```python
    stop = threading.Event()
    beat = threading.Thread(
        target=_heartbeat, args=(store, job.id, owner, stop, lease_seconds), daemon=True
    )
    beat.start()
```

Cooperative-stop hook checks ONLY cancellation (`worker.py:241-242`):

```python
    def should_stop() -> bool:
        return store.jobs.is_cancelled(job.id)
```

Completion path releases with owner guard; `release` returns False safely if
ownership is gone (`worker.py:320-326`).

Conventions: module docstrings carry design rationale — write yours in the
same style. Type annotations, four-space indent, ruff E/F/I/B/UP.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Worker tests | `uv run --extra dev pytest tests/test_worker.py` | all pass |
| Full suite   | `uv run --extra dev pytest` | all pass (~4s) |
| Lint         | `uv run ruff check backend/agentaudit/worker.py tests/test_worker.py` | exit 0 |

## Scope

**In scope**:
- `backend/agentaudit/worker.py`
- `tests/test_worker.py`

**Out of scope** (do NOT touch):
- `backend/agentaudit/core/store.py` — JobQueue SQL semantics are correct;
  the fix is purely in the worker's wiring. Do NOT attempt the
  cancel-vs-done race here either (separate follow-up).
- Heartbeat interval math.

## Git workflow

- Branch: `advisor/003-lease-loss-stop`
- Commit style: short imperative subject (repo example: `Add abort/cancel for queued and running jobs`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a `lost_lease` event and set it from the heartbeat

In `work_once` (around line 291), create a second event alongside `stop`:

```python
    lost_lease = threading.Event()
    beat = threading.Thread(
        target=_heartbeat,
        args=(store, job.id, owner, stop, lease_seconds),
        kwargs={"lost": lost_lease},
        daemon=True,
    )
```

Extend `_heartbeat`'s signature with a keyword parameter
`lost: threading.Event | None = None`; in the heartbeat-failure branch, set
it before returning:

```python
        if not store.jobs.heartbeat(job_id, owner, lease_seconds=lease):
            log.warning("job %s: lease lost, another worker owns it now", job_id)
            if lost is not None:
                lost.set()
            return
```

Keep the default `None` so existing callers/signature stay compatible.

**Verify**: `uv run ruff check backend/agentaudit/worker.py` → exit 0

### Step 2: Make execution observe lease loss

`execute_job` receives its cooperative-stop callback; find where `should_stop`
is defined (around line 241). Thread the event through: extend
`execute_job`'s signature with an optional `lost_lease: threading.Event | None = None`
parameter and change the closure to:

```python
    def should_stop() -> bool:
        return store.jobs.is_cancelled(job.id) or (
            lost_lease is not None and lost_lease.is_set()
        )
```

Update the single call site in `work_once` to pass `lost_lease=lost_lease`.
The existing `JobCancelled` handling in `work_once` then treats a
lease-lost abort like any cooperative stop: partial evidence is released as
`failed` with the cancelled-error marker via the existing paths. Note in the
docstring why lease loss maps onto the same cooperative-stop channel (one
sentence, matching the module's rationale style).

**Verify**: `uv run --extra dev pytest tests/test_worker.py` → all pass

### Step 3: Add the regression test

In `tests/test_worker.py`, following the pattern of the existing
cancel-mid-run test (fake Store or real store per that test's style):
simulate heartbeat failure by making `store.jobs.heartbeat` return False on
first call, let the worker start a multi-test run, and assert:
1. `execute_job` stops early (fewer agent calls than planned tests),
2. the job is released `failed` (or left to reclaim per the existing
   infra-fault semantics — match whatever the cancel path does today),
3. no second full run's worth of evidence is persisted by the losing worker.

Name it to describe behavior, e.g.
`test_lease_loss_stops_execution_and_releases_failed`.

**Verify**: `uv run --extra dev pytest tests/test_worker.py -k lease` → new test passes

## Test plan

- New test per Step 3 in `tests/test_worker.py`, modeled structurally on the
  existing mid-run cancellation test in the same file.
- Verification: full suite `uv run --extra dev pytest` → all pass.

## Done criteria

- [ ] `uv run --extra dev pytest tests/test_worker.py` exits 0 including the new lease-loss test
- [ ] Full suite `uv run --extra dev pytest` exits 0
- [ ] `uv run ruff check backend/agentaudit/worker.py tests/test_worker.py` exits 0
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:
- The excerpts don't match the live code (drift since planning).
- Making `should_stop` observe the event requires touching `core/store.py`
  or changing JobQueue signatures (out of scope — design question).
- The existing cancel-path release semantics differ materially from the
  description (e.g., no `JobCancelled` propagation exists) — needs human
  judgment about which semantics lease-loss should inherit.

## Maintenance notes

- Reviewer should scrutinize: the event must also fire when the heartbeat
  thread dies unexpectedly (it does — `finally: stop.set(); beat.join()` in
  `work_once` runs after execute_job returns; ensure no deadlock if
  `execute_job` finishes before a failed beat sets the event — the event
  simply never sets, which is correct).
- Follow-up explicitly deferred: the cancel-vs-done check-then-act race at
  `worker.py:321-326` (plan separately AFTER this lands; same function).
- Future: if workers gain distributed deployment, consider surfacing
  lease-lost events in run metadata for observability.
