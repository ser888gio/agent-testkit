"""Polling worker: claim a queued job, run it, persist the evidence.

N workers need no coordination and no broker. Each one claims with a lease and
heartbeats while it works; if it dies, the lease expires and another worker
reclaims the job (`Store.jobs.reclaim`).

The worker resolves targets and packs from the database only. It never reads a
filesystem path a tenant supplied, which is what keeps `loader.load_python_module`
off the tenant-reachable path entirely.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable

from agentaudit.core import llm
from agentaudit.core.audit import execute as execute_audit
from agentaudit.core.campaign import CampaignBudget, run_campaign
from agentaudit.core.config import (
    ConfigError,
    HTTPSpec,
    ResponseSpec,
    TargetConfig,
    load_target_dict,
)
from agentaudit.core.discovery import ShapeUnknown, detect_shape, discover, shape_label
from agentaudit.core.egress import (
    EgressError,
    EgressPolicy,
    ValidatedEndpoint,
    validate_endpoint,
)
from agentaudit.core.evolve import build_generator
from agentaudit.core.lifecycle import GENERATED_PREFIX
from agentaudit.core.loader import LoaderError, load_tests_from_rows
from agentaudit.core.profile import AgentProfile
from agentaudit.core.redaction import Redactor
from agentaudit.core.runner import run as run_tests
from agentaudit.core.schema import RunResult, TestCase, TestResult
from agentaudit.core.scoring import ScoreReport, score
from agentaudit.core.store import (
    CANCELLED_ERROR,
    DISCOVERY_PACK_ID,
    TIMEOUT_ERROR,
    JobRow,
    Store,
)

log = logging.getLogger("agentaudit.worker")

DEFAULT_LEASE_SECONDS = 120
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_PER_ORG = 2

# What one adaptive run may spend. Deliberately a server-side constant and not a
# job column: every candidate costs attacker-model calls plus a real run against
# the agent, so a number a browser could raise is a bill a browser could raise.
# Small on purpose -- this rides on top of a full pack run that already happened.
ADAPTIVE_BUDGET = CampaignBudget(
    max_candidates=5, max_kept=3, wall_clock_s=120.0, max_turns=3
)


class PermanentJobError(Exception):
    """A job that will fail identically on every retry.

    Retrying a target that does not exist, or a pack that no longer validates,
    just burns attempts. These fail the job immediately. Everything else is
    treated as an infrastructure fault and left for lease expiry to retry.

    An *agent* failure is neither: `runner.run` turns those into `Status.ERROR`
    results, which are evidence. A job whose agent failed every test is `done`.
    """


class JobCancelled(Exception):
    """Raised by `execute_job` once the audit's `should_stop` has fired.

    Stopping is cooperative: `should_stop` is only polled between tests, so
    this is the earliest point the worker can react. Tests already dispatched
    to the agent still finish; nothing after them starts. When at least one
    test had finished, its partial run is saved first and `run_id` carries it,
    so the job can link the evidence that exists.

    `error` distinguishes the two things that fire the same stop: a user asking
    for a cancel, and the job outrunning its own `timeout_seconds` budget. Both
    end the job the same way, but a timeout is not a cancel and the evidence
    must not claim it was one.
    """

    def __init__(self, job_id: str, run_id: str | None = None, *, error: str = CANCELLED_ERROR):
        super().__init__(job_id)
        self.job_id = job_id
        self.run_id = run_id
        self.error = error


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


def resolve_secret(secret_ref: str | None) -> dict[str, str]:
    """Resolve a target's `secret_ref` into an interpolation mapping.

    Only `env://VAR` today, read from the *worker's* environment, which is
    deployment-owned. The mapping is scoped to one run and passed explicitly to
    the loader; `os.environ` is never mutated, so a concurrent run in another
    thread cannot read another tenant's credential.
    """
    if not secret_ref:
        return {}
    scheme, _, remainder = secret_ref.partition("://")
    if scheme.lower() != "env":
        raise PermanentJobError(f"unsupported secret_ref scheme '{scheme}://'")
    name = remainder.strip()
    if not name or name not in os.environ:
        raise PermanentJobError(f"secret_ref '{secret_ref}' is not provisioned on this worker")
    return {name: os.environ[name]}


def _safe_job_error(store: Store, job: JobRow, message: str) -> str:
    """Remove a run-scoped credential before logging or persisting an error.

    Validation failures can contain interpolated target values (for example an
    invalid endpoint).  Job errors and worker logs are outside the runner's
    evidence redaction path, so scrub the credential at this boundary too.
    """
    try:
        secret_ref = store.get_target_secret_ref(job.org_id, job.target_id)
        secrets = resolve_secret(secret_ref)
    except Exception:  # noqa: BLE001 - error handling must never mask the original error
        secrets = {}
    for value in secrets.values():
        if value:
            message = message.replace(value, "[REDACTED]")
    return message


def _prepare_target(store: Store, job: JobRow) -> tuple[TargetConfig, Redactor, str | None]:
    """Resolve one job's target into everything needed to dial it safely.

    Shared by run and discovery jobs: both reach a live endpoint, so both owe
    the same egress decision, the same resolved-credential redaction, and the
    same pinned address. A second copy of this preamble is a second thing to
    audit.
    """
    try:
        raw_config = store.get_target(job.org_id, job.target_id)
        secret_ref = store.get_target_secret_ref(job.org_id, job.target_id)
        allowed_hosts = store.get_target_allowed_hosts(job.org_id, job.target_id)
    except KeyError as exc:
        raise PermanentJobError(f"unknown target: {exc}") from exc
    except (ConfigError, ValueError) as exc:
        raise PermanentJobError(str(exc)) from exc

    secrets = resolve_secret(secret_ref)
    try:
        target = load_target_dict(raw_config, source=f"target '{job.target_id}'", secrets=secrets)
    except (ConfigError, ValueError) as exc:
        raise PermanentJobError(str(exc)) from exc

    # Egress is decided once, here, before any request leaves the process.
    endpoint = None
    if isinstance(target.agent, HTTPSpec):
        try:
            endpoint = validate_endpoint(
                target.agent.endpoint,
                EgressPolicy.from_iterable(allowed_hosts),
                # Deployment-owned, from the worker's own environment. Never
                # from the target: a tenant-settable bypass is not a bypass fix.
                #
                # ponytail: process-wide, so on a worker where it is set it
                # relaxes the https and private-address checks for *every*
                # org's target, not just the local stub it was set for. That
                # is fine on a single-tenant dev box and is the ceiling here:
                # if a shared worker ever needs it, scope it to an explicit
                # target-id allowlist rather than widening it further.
                allow_private=os.environ.get("AGENTAUDIT_EGRESS_ALLOW_LOCAL") == "1",
            )
        except EgressError as exc:
            raise PermanentJobError(f"endpoint rejected by egress policy: {exc}") from exc

    # A resolved credential is a literal the redactor must mask even though it
    # never appears in the stored config. The Redactor stays the last line of
    # defense, not the first.
    redactor = Redactor(
        target.evidence.redact.model_copy(
            update={"literals": [*target.evidence.redact.literals, *secrets.values()]}
        )
    )
    return target, redactor, endpoint


def execute_discovery(store: Store, job: JobRow) -> None:
    """Probe the target and replace its stored profile.

    Discovery produces a profile, not a run, so this writes nothing to `runs`
    and the job finishes with no `run_id`. Probes go through `runner.run` bound
    to the same egress decision and redactor as an audit would use -- discovery
    reaches a live partner endpoint and gets no shortcut around that.
    """
    store.jobs.set_phase(job.id, "connecting")
    target, redactor, endpoint = _prepare_target(store, job)

    def bound_run(cfg: TargetConfig, cases: list) -> RunResult:
        return run_tests(cfg, cases, redactor=redactor, endpoint=endpoint)

    store.jobs.set_phase(job.id, "shaping")
    target = _confirm_request_shape(store, job, target, bound_run)
    store.jobs.set_phase(job.id, "probing")
    profile = discover(target, runner=bound_run)
    store.jobs.set_phase(job.id, "profiling")
    store.save_target_profile(job.org_id, job.target_id, profile)
    log.info("job %s: profiled target %s", job.id, job.target_id)


def _confirm_request_shape(
    store: Store, job: JobRow, target: TargetConfig, bound_run
) -> TargetConfig:
    """Prove the prompt reaches the agent, and persist the shape that got it there.

    A target registered through the dashboard carries a guessed request shape:
    the form asks for an endpoint, not a body schema. A wrong guess does not
    error -- the agent answers a prompt it never received and the run scores
    that reply -- so the shape is confirmed here, against the live endpoint,
    before any pack is ever run against it.

    Failure is permanent on purpose. A target whose prompt does not arrive
    cannot produce evidence, and reporting that as a profile with a note would
    leave a registered agent that silently scores nothing.
    """
    if not isinstance(target.agent, HTTPSpec):
        return target
    try:
        request, text_path = detect_shape(target, runner=bound_run)
    except ShapeUnknown as exc:
        raise PermanentJobError(str(exc)) from exc

    confirmed = target.model_copy(
        update={
            "agent": target.agent.model_copy(
                update={"request": request, "response": ResponseSpec(text_path=text_path)}
            )
        },
        deep=True,
    )
    if (request, text_path) == (target.agent.request, target.agent.response.text_path):
        return confirmed

    # Persist onto the *stored* config, which is un-interpolated: re-saving the
    # resolved `target` would write a secret back into the row that T15 keeps
    # literal. Only the two shape keys are replaced.
    raw = store.get_target(job.org_id, job.target_id)
    raw["agent"]["request"] = request
    raw["agent"].setdefault("response", {})["text_path"] = text_path
    store.save_target(
        job.org_id,
        job.target_id,
        job.target_id,
        raw,
        secret_ref=store.get_target_secret_ref(job.org_id, job.target_id),
        allowed_hosts=store.get_target_allowed_hosts(job.org_id, job.target_id),
    )
    log.info(
        "job %s: target %s answers on %s", job.id, job.target_id, shape_label(request, text_path)
    )
    return confirmed


def _apply_selection(job: JobRow, tests: list) -> list:
    """Narrow a pack to the tests the job selected.

    A selection naming ids the pack does not contain is a permanent failure
    rather than a quietly smaller run: the caller asked for coverage that does
    not exist, and silently running less would report a pass for tests that
    never executed.
    """
    if not job.test_ids_json:
        return tests
    wanted = set(json.loads(job.test_ids_json))
    selected = [t for t in tests if getattr(t, "id", None) in wanted]
    missing = wanted - {getattr(t, "id", None) for t in tests}
    if missing:
        raise PermanentJobError(
            f"selected test(s) not in pack '{job.pack_id}': {', '.join(sorted(missing))}"
        )
    if not selected:
        raise PermanentJobError("test selection matched no tests")
    return selected


def _tenant_llm_config(store: Store, org_id: str) -> llm.LLMConfig | None:
    """This org's own attacker/judge models, or None to fall back to the deployment's.

    The key is read here and handed to the config object rather than exported to
    `os.environ`: workers run jobs for several orgs concurrently, and a process
    env var is shared by all of them.
    """
    rows = store.get_llm_secrets(org_id)
    if not rows:
        return None

    def role(name: str) -> llm.RoleConfig | None:
        row = rows.get(name)
        if row is None:
            return None
        return llm.RoleConfig(
            model=row["model"], endpoint=row["endpoint"], api_key_literal=row["api_key"]
        )

    return llm.LLMConfig(attacker=role("attacker"), judge=role("judge"))


def execute_job(
    store: Store, job: JobRow, *, lost_lease: threading.Event | None = None
) -> str | None:
    """Resolve, run, score, and persist one claimed job. Returns the run id.

    Returns None for a discovery job, which updates a profile instead of
    producing a run.

    Checks `store.jobs.is_cancel_requested` between tests; a cancelled job
    still saves whatever ran as a (shorter) run, same as any other partial
    evidence. `work_once` is what turns that into the job's terminal state.
    """
    with llm.override(_tenant_llm_config(store, job.org_id)):
        return _execute_job(store, job, lost_lease=lost_lease)


def _execute_job(
    store: Store, job: JobRow, *, lost_lease: threading.Event | None = None
) -> str | None:
    if job.pack_id == DISCOVERY_PACK_ID:
        execute_discovery(store, job)
        return None

    # Phase transitions bracket the stages that happen before the first test
    # result, which is the window the dashboard used to render as a bare
    # spinner. Each is one UPDATE on the job row; the run is unaffected.
    store.jobs.set_phase(job.id, "connecting")
    target, redactor, endpoint = _prepare_target(store, job)

    # A target registered through the form carries a *guessed* request shape
    # (intake fills `input_path`, default "input"). A wrong guess is not an
    # error: the agent answers a prompt it never received and this run scores
    # that reply. `profiled_at` is null until discovery has confirmed the shape
    # against the live endpoint, so confirm it here for a target that has never
    # been profiled -- register -> run must not be a legal path to a green run
    # that tested nothing.
    #
    # The same row carries the profile the planner ranks against, so one read
    # answers both questions: an unprofiled target needs its shape confirmed,
    # and a profiled one can skip re-probing the endpoint below.
    stored = store.get_target_profile(job.org_id, job.target_id)
    if stored is None:
        target = _confirm_request_shape(
            store,
            job,
            target,
            lambda cfg, cases: run_tests(cfg, cases, redactor=redactor, endpoint=endpoint),
        )
    profile = stored[0] if stored else None

    try:
        tests = load_tests_from_rows(store.get_pack_tests(job.org_id, job.pack_id))
    except KeyError as exc:
        raise PermanentJobError(f"unknown pack: {exc}") from exc
    except (LoaderError, ValueError) as exc:
        raise PermanentJobError(str(exc)) from exc

    tests = _apply_selection(job, tests)
    store.jobs.set_phase(job.id, "planning")
    transforms = json.loads(job.attack_transforms_json) if job.attack_transforms_json else []

    # Live progress so the dashboard can show a run moving. It lands on the
    # job row, never in `runs`: a half-written run is not evidence, and every
    # reader of `runs` would otherwise have to learn to exclude one.
    #
    # The total comes from `on_plan`, not len(tests): the planner narrows the
    # list and attack transforms expand it, so the count here is not the count
    # that runs.
    def count(planned, _harness, _unexecuted) -> None:
        store.jobs.start_progress(job.id, len(planned))
        store.jobs.set_phase(job.id, "testing")

    def expanding(_names) -> None:
        store.jobs.set_phase(job.id, "expanding")

    def note(_index: int, result) -> None:
        store.jobs.record_progress(job.id, result.test_id, result.status.value)

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
        profile=profile,
        attack_transforms=transforms,
        on_plan=count,
        on_expand=expanding,
        on_result=note,
        should_stop=should_stop,
    )
    if lost_lease is not None and lost_lease.is_set():
        # Another worker owns this job now. Persist nothing: its run would be a
        # duplicate evidence row for a job we no longer hold.
        raise LeaseLost(job.id)
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
    result, report = audit.result, audit.report
    if audit.unexecuted:
        log.info(
            "job %s: %d selected test(s) belong to external tools and are not executed here",
            job.id,
            len(audit.unexecuted),
        )

    if job.adaptive:
        store.jobs.set_phase(job.id, "attacking")
        result, report = _attack_adaptively(
            store,
            job,
            target,
            result,
            profile=profile,
            redactor=redactor,
            endpoint=endpoint,
            should_stop=should_stop,
        )

    store.jobs.set_phase(job.id, "scoring")
    store.save_run(job.org_id, target, result, report, job.created_by, plan=audit.plan)
    return result.run_id


def _attack_adaptively(
    store: Store,
    job: JobRow,
    target: TargetConfig,
    result: RunResult,
    *,
    profile: AgentProfile | None,
    redactor: Redactor,
    endpoint: ValidatedEndpoint | None,
    should_stop: Callable[[], bool],
) -> tuple[RunResult, ScoreReport]:
    """Generate new attacks against this agent and fold them into the run.

    The campaign runs every candidate it keeps, so the results already exist by
    the time it returns -- capturing them through `run_fn` costs no extra agent
    calls, and appending them mirrors how `audit.execute` already folds in
    external-tool results.

    Failing to generate is not a failed run. An unconfigured or unreachable
    model, a rate limit, a budget that produced nothing: the pack's evidence
    stands on its own, so this logs and returns it unchanged rather than
    turning a green run red on an LLM outage.

    Generated tests also go to the `generated` pack, the same review queue
    `agentaudit evolve` feeds -- a candidate that landed is a finding a human
    should decide to keep, not something this run silently discards.
    """
    captured: list[TestResult] = []

    class _Stopped(Exception):
        """Abort the campaign between candidates."""

    def run_fn(tests: list[TestCase]) -> RunResult:
        # Cancel and timeout must reach this stage too: the campaign holds the
        # job for its whole wall clock, and `evolve` has no stop hook of its
        # own. Raising here is the seam -- the guard below catches it, and the
        # candidates that already ran are kept.
        if should_stop():
            raise _Stopped
        run = run_tests(target, tests, redactor=redactor, endpoint=endpoint)
        captured.extend(run.results)
        return run

    # One guard around the whole stage, building the generator included: a
    # malformed llm.yaml raises here just as readily as a rate limit does, and
    # both mean the same thing -- no generation this run, evidence unaffected.
    try:
        generator = build_generator()
        if generator is None:
            log.info("job %s: adaptive requested but no attacker model is configured", job.id)
            return result, score(result)
        campaign = run_campaign(
            generator,
            run_fn,
            budget=ADAPTIVE_BUDGET,
            profile=profile,
        )
    except _Stopped:
        log.info("job %s: adaptive attack stopped early; keeping what ran", job.id)
        if captured:
            merged = result.model_copy(update={"results": [*result.results, *captured]})
            return merged, score(merged)
        return result, score(result)
    except Exception:  # noqa: BLE001 - a generator is a network call
        log.exception("job %s: adaptive attack failed; keeping the pack's evidence", job.id)
        # Candidates that ran before the failure are still evidence.
        if captured:
            merged = result.model_copy(update={"results": [*result.results, *captured]})
            return merged, score(merged)
        return result, score(result)

    if campaign.kept:
        store.ensure_pack(job.org_id, GENERATED_PREFIX, "Generated tests (provisional)")
        for row in campaign.as_pack_rows():
            # A generated id is a hash of its probe, so regenerating the same
            # attack in a later run collides by design -- that is the id being
            # stable, not an error. The candidate is already in the pack; keep
            # its run evidence and move on rather than failing the job.
            try:
                store.save_pack_test(job.org_id, GENERATED_PREFIX, row, created_by="adaptive")
            except LoaderError:
                log.debug("job %s: %s already queued for review", job.id, row.get("id"))

    log.info(
        "job %s: adaptive generated %d candidate(s), kept %d, %d landed (%s)",
        job.id,
        campaign.candidates_generated,
        len(campaign.kept),
        sum(1 for c in campaign.kept if c.landed),
        campaign.stopped_because,
    )
    if not captured:
        return result, score(result)

    merged = result.model_copy(update={"results": [*result.results, *captured]})
    return merged, score(merged)


def work_once(
    store: Store,
    owner: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_per_org: int | None = DEFAULT_MAX_PER_ORG,
) -> JobRow | None:
    """Claim and process at most one job. Returns it, or None if the queue was empty."""
    job = store.jobs.claim(owner, lease_seconds=lease_seconds, max_per_org=max_per_org)
    if job is None:
        return None

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
        # 'expired' is its own terminal state, so a timeout keeps it whether or
        # not partial evidence exists. A cancel that produced evidence stays
        # 'failed', its error text marking the linked run partial.
        log.info("job %s: %s", job.id, exc.error)
        if exc.error == TIMEOUT_ERROR:
            store.jobs.release(job.id, owner, state="expired", run_id=exc.run_id, error=exc.error)
        elif exc.run_id:
            store.jobs.release(job.id, owner, state="failed", run_id=exc.run_id, error=exc.error)
        else:
            store.jobs.release(job.id, owner, state="cancelled")
    except PermanentJobError as exc:
        error = _safe_job_error(store, job, str(exc))
        log.warning("job %s failed permanently: %s", job.id, error)
        store.jobs.release(job.id, owner, state="failed", error=error)
    except Exception:
        # Infrastructure fault. Deliberately not released: the lease expires and
        # `reclaim_jobs` retries it, up to the attempt ceiling. Releasing it as
        # failed here would turn a transient database blip into a dead job.
        # Do not emit the original exception: it can contain an interpolated
        # credential. The lease/retry path retains the failure semantics without
        # putting secrets in logs.
        log.error("job %s hit an infrastructure fault; leaving it to lease expiry", job.id)
    else:
        if store.jobs.is_cancelled(job.id):
            store.jobs.release(job.id, owner, state="failed", run_id=run_id, error=CANCELLED_ERROR)
        else:
            store.jobs.release(job.id, owner, state="done", run_id=run_id)
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
    store = Store(db or os.environ.get("AGENTAUDIT_DB", "database/agentaudit.db"))
    stop = stop or threading.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: stop.set())
        except ValueError:
            pass  # not the main thread; the caller owns shutdown

    log.info("worker %s polling", owner)
    try:
        while not stop.is_set():
            store.jobs.reclaim(max_attempts=max_attempts)
            job = work_once(store, owner, lease_seconds=lease_seconds, max_per_org=max_per_org)
            if job is None:
                stop.wait(poll_seconds)
    finally:
        store.close()
        log.info("worker %s stopped", owner)


if __name__ == "__main__":  # pragma: no cover
    main()
