"""Polling worker: claim a queued job, run it, persist the evidence.

N workers need no coordination and no broker. Each one claims with a lease and
heartbeats while it works; if it dies, the lease expires and another worker
reclaims the job (`Store.reclaim_jobs`).

The worker resolves targets and packs from the database only. It never reads a
filesystem path a tenant supplied, which is what keeps `loader.load_python_module`
off the tenant-reachable path entirely.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import uuid

# Registers the built-in sandboxes before `build_sandbox` is ever called, same
# as cli.py and web/app.py. Not dead imports.
import agentkit.domains.email.sandbox  # noqa: F401
import agentkit.domains.treasury.sandbox  # noqa: F401
from agentkit.core.config import ConfigError, load_target_dict
from agentkit.core.loader import LoaderError, load_tests_from_rows
from agentkit.core.runner import run as run_tests
from agentkit.core.scoring import score
from agentkit.core.store import JobRow, Store

log = logging.getLogger("agentkit.worker")

DEFAULT_LEASE_SECONDS = 120
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_PER_ORG = 2


class PermanentJobError(Exception):
    """A job that will fail identically on every retry.

    Retrying a target that does not exist, or a pack that no longer validates,
    just burns attempts. These fail the job immediately. Everything else is
    treated as an infrastructure fault and left for lease expiry to retry.

    An *agent* failure is neither: `runner.run` turns those into `Status.ERROR`
    results, which are evidence. A job whose agent failed every test is `done`.
    """


def _heartbeat(store: Store, job_id: str, owner: str, stop: threading.Event, lease: int) -> None:
    # Extend well inside the lease so one slow beat does not lose the job.
    interval = max(lease / 4, 1.0)
    while not stop.wait(interval):
        if not store.heartbeat_job(job_id, owner, lease_seconds=lease):
            log.warning("job %s: lease lost, another worker owns it now", job_id)
            return


def execute_job(store: Store, job: JobRow) -> str:
    """Resolve, run, score, and persist one claimed job. Returns the run id."""
    try:
        raw_config = store.get_target(job.org_id, job.target_id)
        tests = load_tests_from_rows(store.get_pack_tests(job.org_id, job.pack_id))
    except KeyError as exc:
        raise PermanentJobError(f"unknown target or pack: {exc}") from exc
    except (ConfigError, LoaderError, ValueError) as exc:
        raise PermanentJobError(str(exc)) from exc

    try:
        target = load_target_dict(raw_config, source=f"target '{job.target_id}'")
    except (ConfigError, ValueError) as exc:
        raise PermanentJobError(str(exc)) from exc

    result = run_tests(target, tests)
    report = score(result)
    store.save_run(job.org_id, target, result, report, job.created_by)
    return result.run_id


def work_once(
    store: Store,
    owner: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_per_org: int | None = DEFAULT_MAX_PER_ORG,
) -> JobRow | None:
    """Claim and process at most one job. Returns it, or None if the queue was empty."""
    job = store.claim_job(owner, lease_seconds=lease_seconds, max_per_org=max_per_org)
    if job is None:
        return None

    stop = threading.Event()
    beat = threading.Thread(
        target=_heartbeat, args=(store, job.id, owner, stop, lease_seconds), daemon=True
    )
    beat.start()
    try:
        run_id = execute_job(store, job)
    except PermanentJobError as exc:
        log.warning("job %s failed permanently: %s", job.id, exc)
        store.release_job(job.id, owner, state="failed", error=str(exc))
    except Exception:
        # Infrastructure fault. Deliberately not released: the lease expires and
        # `reclaim_jobs` retries it, up to the attempt ceiling. Releasing it as
        # failed here would turn a transient database blip into a dead job.
        log.exception("job %s hit an infrastructure fault, leaving it to lease expiry", job.id)
    else:
        store.release_job(job.id, owner, state="done", run_id=run_id)
    finally:
        stop.set()
        beat.join(timeout=5)
    return job


def main(
    db: str | None = None,
    *,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_per_org: int | None = DEFAULT_MAX_PER_ORG,
    stop: threading.Event | None = None,
) -> None:
    """Poll until signalled. `stop` is injectable so tests need no signals."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    owner = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    store = Store(db or os.environ.get("AGENTKIT_DB", "database/agentkit.db"))
    stop = stop or threading.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: stop.set())
        except ValueError:
            pass  # not the main thread; the caller owns shutdown

    log.info("worker %s polling", owner)
    try:
        while not stop.is_set():
            store.reclaim_jobs(max_attempts=max_attempts)
            job = work_once(store, owner, lease_seconds=lease_seconds, max_per_org=max_per_org)
            if job is None:
                stop.wait(poll_seconds)
    finally:
        store.close()
        log.info("worker %s stopped", owner)


if __name__ == "__main__":  # pragma: no cover
    main()
