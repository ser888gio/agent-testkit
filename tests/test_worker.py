import threading
import time

import pytest

import agentaudit.core.audit as audit_module
from agentaudit.core.store import JobQueue, Store
from agentaudit.worker import JobCancelled, PermanentJobError, execute_job, main, work_once

MODULE = "tests.test_worker"

_TARGET_CONFIG = {
    "id": "worker-target",
    "agent": {"type": "callable", "callable": f"{MODULE}:create_agent"},
}
_TEST = {
    "id": "w.pass.case",
    "category": "reliability",
    "input": "hi",
    "assertions": [{"name": "status_ok"}],
}


def _agent(input: str) -> str:
    return "ok"


def create_agent():
    return _agent


def create_broken_agent():
    def _broken(input: str) -> str:
        raise RuntimeError("agent exploded")

    return _broken


def _store_with_job(tmp_path, org: str = "org-a", **kw) -> tuple[Store, str]:
    store = Store(str(tmp_path / "worker.db"))
    store.save_target(org, "worker-target", "Worker Target", _TARGET_CONFIG)
    store.save_pack(org, "pack-1", "Pack One", [_TEST])
    job_id = store.jobs.enqueue(org, "worker-target", "pack-1", **kw)
    return store, job_id


def test_work_once_runs_the_job_and_persists_the_run(tmp_path):
    store, job_id = _store_with_job(tmp_path)

    assert work_once(store, "w1").id == job_id

    job = store.jobs.get("org-a", job_id)
    assert job.state == "done"
    assert job.lease_owner is None
    assert job.finished_at is not None

    runs = store.list_runs("org-a")
    assert len(runs) == 1
    assert runs[0].id == job.run_id


def test_work_once_returns_none_on_an_empty_queue(tmp_path):
    store = Store(str(tmp_path / "empty.db"))

    assert work_once(store, "w1") is None


def test_unknown_target_fails_permanently_without_burning_retries(tmp_path):
    store = Store(str(tmp_path / "missing.db"))
    job_id = store.jobs.enqueue("org-a", "nope", "also-nope")

    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "failed"
    assert "unknown target" in job.error
    assert store.jobs.reclaim() == 0


def test_resolved_secret_is_not_written_to_job_errors_or_logs(tmp_path, monkeypatch, caplog):
    secret = "worker-secret-not-for-storage"
    monkeypatch.setenv("WORKER_SECRET", secret)
    store = Store(str(tmp_path / "secret-error.db"))
    store.save_target(
        "org-a",
        "bad-endpoint",
        "Bad endpoint",
        {"id": "bad-endpoint", "agent": {"type": "http", "endpoint": "${WORKER_SECRET}"}},
        secret_ref="env://WORKER_SECRET",
        allowed_hosts=["agent.example.test"],
    )
    store.save_pack("org-a", "pack-1", "Pack One", [_TEST])
    job_id = store.jobs.enqueue("org-a", "bad-endpoint", "pack-1")

    with caplog.at_level("WARNING", logger="agentaudit.worker"):
        work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert secret not in (job.error or "")
    assert secret not in caplog.text


def test_execute_job_raises_permanent_for_a_foreign_orgs_target(tmp_path):
    store, _ = _store_with_job(tmp_path, org="org-a")
    stolen = store.jobs.enqueue("org-b", "worker-target", "pack-1")
    job = store.jobs.get("org-b", stolen)

    with pytest.raises(PermanentJobError):
        execute_job(store, job)


def test_infrastructure_faults_are_left_for_lease_expiry(tmp_path, monkeypatch):
    store, job_id = _store_with_job(tmp_path)
    def _explode(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr("agentaudit.core.audit.run_tests", _explode)

    work_once(store, "w1", lease_seconds=-1)

    # Still 'running' and unreleased -- the reclaim sweep owns the retry.
    assert store.jobs.get("org-a", job_id).state == "running"
    assert store.jobs.reclaim() == 1
    assert store.jobs.get("org-a", job_id).state == "queued"


def test_agent_failures_are_evidence_not_job_failures(tmp_path):
    """A crashing agent is a Status.ERROR result, never a retryable job failure."""
    store = Store(str(tmp_path / "agentfail.db"))
    store.save_target(
        "org-a",
        "boom",
        "Exploding Agent",
        {"id": "boom", "agent": {"type": "callable", "callable": f"{MODULE}:create_broken_agent"}},
    )
    store.save_pack("org-a", "pack-1", "Pack One", [_TEST])
    job_id = store.jobs.enqueue("org-a", "boom", "pack-1")

    work_once(store, "w1")

    assert store.jobs.get("org-a", job_id).state == "done"
    run, _ = store.get_run("org-a", store.jobs.get("org-a", job_id).run_id)
    assert [r.status.value for r in run.results] == ["error"]
    assert store.jobs.reclaim() == 0


def test_cancel_requested_mid_run_stops_the_job_and_keeps_partial_evidence(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "cancel.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    tests = [{**_TEST, "id": f"w.pass.case.{n}"} for n in range(2)]
    store.save_pack("org-a", "pack-1", "Pack One", tests)
    job_id = store.jobs.enqueue("org-a", "worker-target", "pack-1")

    # Simulate a cancel request arriving mid-run: flag the job right after the
    # first test's progress lands, the same point a real caller's request
    # would race against.
    original_record_progress = JobQueue.record_progress

    def _record_then_cancel(self, job_id_, test_id, status):
        original_record_progress(self, job_id_, test_id, status)
        self.request_cancel("org-a", job_id_)

    monkeypatch.setattr(JobQueue, "record_progress", _record_then_cancel)

    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "failed"
    assert job.error == "cancelled by user"
    assert job.run_id is not None

    run, _ = store.get_run("org-a", job.run_id)
    assert [r.test_id for r in run.results] == ["w.pass.case.0"]


def test_a_worker_run_persists_the_plan_that_selected_its_tests(tmp_path):
    """A hosted run is evidence too: `report --format plan` must not say "no planner"."""
    store, job_id = _store_with_job(tmp_path)

    work_once(store, "w1")

    run_id = store.jobs.get("org-a", job_id).run_id
    harness = store.get_run_plan("org-a", run_id)
    assert harness is not None
    assert harness.profile.id == "worker-target"
    assert _TEST["id"] in harness.selected_ids()
    # Every selection has to explain itself; that rationale is the whole point.
    assert all(choice.reasons for choice in harness.selected)

    # The stored evidence covers exactly the local half of the plan. Adapter-backed
    # selections are ranked but executed out of band, so a run that claimed results
    # for them would be reporting coverage that does not exist.
    run, _ = store.get_run("org-a", run_id)
    local = {c.test_id for c in harness.selected if c.source == "local"}
    assert {r.test_id for r in run.results} == local


def test_discovery_reuses_the_jobs_egress_decision(tmp_path, monkeypatch):
    """Discovery must not open a second execution path around the egress check."""
    seen: list[object] = []
    real_run = audit_module.run_tests

    def spy(cfg, cases, **kwargs):
        seen.append(kwargs.get("endpoint", "MISSING"))
        return real_run(cfg, cases, **kwargs)

    monkeypatch.setattr(audit_module, "run_tests", spy)
    store, _ = _store_with_job(tmp_path)

    work_once(store, "w1")

    # Probe calls and the graded run alike: every one carries the bound endpoint
    # keyword, so none of them bypassed validate_endpoint above.
    assert seen, "expected the worker to execute something"
    assert "MISSING" not in seen


def test_cancel_requested_before_the_run_starts_stops_it_before_the_first_test(tmp_path):
    """`should_stop` is polled at the top of the loop, so a cancel that lands before
    the worker starts skips every test rather than running one first."""
    second_test = {**_TEST, "id": "w.pass.case.2"}
    store = Store(str(tmp_path / "cancel.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    store.save_pack("org-a", "pack-1", "Pack One", [_TEST, second_test])
    job_id = store.jobs.enqueue("org-a", "worker-target", "pack-1")
    store.jobs.claim("w1")

    store.jobs.request_cancel("org-a", job_id)

    with pytest.raises(JobCancelled):
        execute_job(store, store.jobs.get("org-a", job_id))

    job = store.jobs.get("org-a", job_id)
    # execute_job itself doesn't release the lease; work_once does that.
    assert job.state == "running"
    assert job.tests_done == 0


def test_work_once_releases_a_cancelled_job_without_a_run(tmp_path, monkeypatch):
    second_test = {**_TEST, "id": "w.pass.case.2"}
    store = Store(str(tmp_path / "cancel2.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    store.save_pack("org-a", "pack-1", "Pack One", [_TEST, second_test])
    job_id = store.jobs.enqueue("org-a", "worker-target", "pack-1")

    real_claim = JobQueue.claim

    def claim_then_cancel(self, owner, **kw):
        job = real_claim(self, owner, **kw)
        if job is not None:
            store.jobs.request_cancel("org-a", job.id)
        return job

    monkeypatch.setattr(JobQueue, "claim", claim_then_cancel)
    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "cancelled"
    assert job.run_id is None
    assert store.list_runs("org-a") == []


def test_request_cancel_on_a_queued_job_finishes_it_immediately(tmp_path):
    store, job_id = _store_with_job(tmp_path)

    assert store.jobs.request_cancel("org-a", job_id) == "cancelled"

    job = store.jobs.get("org-a", job_id)
    assert job.state == "cancelled"
    assert work_once(store, "w1") is None  # nothing left to claim


def test_request_cancel_on_a_finished_job_is_a_no_op(tmp_path):
    store, job_id = _store_with_job(tmp_path)
    work_once(store, "w1")

    assert store.jobs.request_cancel("org-a", job_id) == "done"
    assert store.jobs.get("org-a", job_id).state == "done"


def test_per_org_cap_stops_one_partner_starving_another(tmp_path):
    store = Store(str(tmp_path / "cap.db"))
    for _ in range(3):
        store.jobs.enqueue("org-a", "t", "p")
    b_job = store.jobs.enqueue("org-b", "t", "p")

    claimed = [store.jobs.claim(f"w{i}", max_per_org=2) for i in range(3)]

    assert [j.org_id for j in claimed] == ["org-a", "org-a", "org-b"]
    assert claimed[2].id == b_job


def test_heartbeat_keeps_a_long_job_from_being_reclaimed(tmp_path, monkeypatch):
    store, job_id = _store_with_job(tmp_path)
    monkeypatch.setattr("agentaudit.core.audit.run_tests", _slow_run)

    done = threading.Thread(target=work_once, args=(store, "w1"), kwargs={"lease_seconds": 4})
    done.start()
    time.sleep(2.5)
    reclaimed = store.jobs.reclaim()
    done.join(timeout=10)

    assert reclaimed == 0
    assert store.jobs.get("org-a", job_id).state == "done"


def _slow_run(target, tests, **kw):
    from agentaudit.core.runner import run as real_run

    time.sleep(3)
    return real_run(target, tests, **kw)


def test_main_stops_when_signalled(tmp_path):
    store, job_id = _store_with_job(tmp_path)
    store.close()
    stop = threading.Event()

    thread = threading.Thread(
        target=main, args=(str(tmp_path / "worker.db"),), kwargs={"stop": stop}
    )
    thread.start()
    deadline = time.time() + 10
    check = Store(str(tmp_path / "worker.db"))
    while time.time() < deadline:
        if check.jobs.get("org-a", job_id).state == "done":
            break
        time.sleep(0.1)
    stop.set()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert check.jobs.get("org-a", job_id).state == "done"


def test_a_discovery_job_writes_a_profile_and_no_run(tmp_path):
    """Discovery produces a profile, not evidence: `runs` must stay untouched."""
    store = Store(str(tmp_path / "discovery.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    job_id = store.jobs.enqueue_discovery("org-a", "worker-target")

    assert work_once(store, "w1").id == job_id

    job = store.jobs.get("org-a", job_id)
    assert job.state == "done"
    # A discovery job has no run to point at.
    assert job.run_id is None
    assert store.list_runs("org-a") == []

    stored = store.get_target_profile("org-a", "worker-target")
    assert stored is not None
    profile, profiled_at = stored
    assert profile.id == "worker-target"
    assert profile.interface == "callable"
    assert profiled_at


def test_discovery_probes_carry_the_bound_endpoint(tmp_path, monkeypatch):
    """The discovery job owes the same egress decision a run does."""
    import agentaudit.worker as worker_module

    seen: list[object] = []
    real_run = worker_module.run_tests

    def spy(cfg, cases, **kwargs):
        seen.append(kwargs.get("endpoint", "MISSING"))
        return real_run(cfg, cases, **kwargs)

    monkeypatch.setattr(worker_module, "run_tests", spy)
    store = Store(str(tmp_path / "discovery-egress.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    store.jobs.enqueue_discovery("org-a", "worker-target")

    work_once(store, "w1")

    assert seen, "expected the discovery job to probe"
    assert "MISSING" not in seen


def test_rediscovery_replaces_the_stored_profile(tmp_path):
    """A profile describes the agent now, so it overwrites rather than appends."""
    store = Store(str(tmp_path / "rediscovery.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)

    store.jobs.enqueue_discovery("org-a", "worker-target")
    work_once(store, "w1")
    first = store.get_target_profile("org-a", "worker-target")

    store.jobs.enqueue_discovery("org-a", "worker-target")
    work_once(store, "w2")
    second = store.get_target_profile("org-a", "worker-target")

    assert first is not None and second is not None
    assert second[1] >= first[1]


def test_profile_is_none_before_discovery_and_unknown_target_raises(tmp_path):
    store = Store(str(tmp_path / "no-profile.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)

    assert store.get_target_profile("org-a", "worker-target") is None
    with pytest.raises(KeyError):
        store.get_target_profile("org-a", "nope")


_SECOND_TEST = {
    "id": "w.second.case",
    "category": "reliability",
    "input": "hi",
    "assertions": [{"name": "status_ok"}],
}


def _store_with_two_tests(tmp_path, **kw) -> tuple[Store, str]:
    store = Store(str(tmp_path / "selection.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    store.save_pack("org-a", "pack-1", "Pack One", [_TEST, _SECOND_TEST])
    job_id = store.jobs.enqueue("org-a", "worker-target", "pack-1", **kw)
    return store, job_id


def test_a_job_runs_only_the_tests_it_selected(tmp_path):
    store, job_id = _store_with_two_tests(tmp_path, test_ids=["w.second.case"])

    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "done"
    rr, _report = store.get_run("org-a", job.run_id)
    assert [r.test_id for r in rr.results] == ["w.second.case"]


def test_no_selection_still_runs_the_whole_pack(tmp_path):
    store, job_id = _store_with_two_tests(tmp_path)

    work_once(store, "w1")

    rr, _report = store.get_run("org-a", store.jobs.get("org-a", job_id).run_id)
    assert {r.test_id for r in rr.results} == {"w.pass.case", "w.second.case"}


def test_selecting_a_test_outside_the_pack_fails_loudly(tmp_path):
    """Silently running less would report a pass for tests that never ran."""
    store, job_id = _store_with_two_tests(tmp_path, test_ids=["w.pass.case", "ghost.case"])

    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "failed"
    assert "ghost.case" in job.error
    assert job.run_id is None


def test_an_empty_selection_is_rejected_at_enqueue(tmp_path):
    """A run of nothing scored as a pass is evidence of coverage that never happened."""
    store = Store(str(tmp_path / "empty-selection.db"))

    with pytest.raises(ValueError, match="at least one test"):
        store.jobs.enqueue("org-a", "t", "p", test_ids=[])


def test_selection_survives_the_queue(tmp_path):
    """The worker resolves jobs from the database alone, so the choice must persist."""
    store, job_id = _store_with_two_tests(tmp_path, test_ids=["w.second.case"])

    import json as _json

    assert _json.loads(store.jobs.get("org-a", job_id).test_ids_json) == ["w.second.case"]


def test_a_running_job_reports_progress_without_writing_a_run(tmp_path):
    """The whole point of progress-on-the-job: `runs` stays untouched mid-flight."""
    store, job_id = _store_with_two_tests(tmp_path)
    seen: list[tuple[int, int, list]] = []

    real_record = store.jobs.record_progress

    def spy(jid, test_id, status):
        real_record(jid, test_id, status)
        job = store.jobs.get("org-a", jid)
        # Mid-run: progress is visible, but no run exists to be mistaken for
        # evidence and no score has been computed.
        seen.append((job.tests_done, job.tests_total, store.list_runs("org-a")))

    store.jobs.record_progress = spy
    work_once(store, "w1")

    assert seen, "expected per-test progress"
    assert [s[0] for s in seen] == [1, 2], "tests_done must climb"
    assert all(s[1] == 2 for s in seen), "total is known up front"
    assert all(s[2] == [] for s in seen), "no run may exist while one is in flight"

    # The run lands exactly once, at the end.
    assert len(store.list_runs("org-a")) == 1


def test_progress_records_each_outcome(tmp_path):
    store, job_id = _store_with_two_tests(tmp_path)

    work_once(store, "w1")

    import json as _json

    recent = _json.loads(store.jobs.get("org-a", job_id).progress_json)
    assert {e["test_id"] for e in recent} == {"w.pass.case", "w.second.case"}
    assert all(e["status"] in ("passed", "failed", "error", "skipped") for e in recent)


def test_progress_window_is_bounded(tmp_path):
    """A long run must not grow the job row without bound."""
    store = Store(str(tmp_path / "window.db"))
    store.jobs.enqueue("org-a", "t", "p")
    job_id = store.jobs.list_recent("org-a")[0].id
    store.jobs.start_progress(job_id, 100)

    for i in range(JobQueue.PROGRESS_WINDOW + 5):
        store.jobs.record_progress(job_id, f"t.{i}", "passed")

    import json as _json

    job = store.jobs.get("org-a", job_id)
    recent = _json.loads(job.progress_json)
    assert len(recent) == JobQueue.PROGRESS_WINDOW
    # The window keeps the newest, and the counter still sees everything.
    assert recent[-1]["test_id"] == f"t.{JobQueue.PROGRESS_WINDOW + 4}"
    assert job.tests_done == JobQueue.PROGRESS_WINDOW + 5


def test_a_failing_progress_callback_does_not_lose_the_run(tmp_path):
    """Evidence matters; a dropped status update does not."""
    store, job_id = _store_with_two_tests(tmp_path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("progress backend down")

    store.jobs.record_progress = boom
    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "done"
    rr, _report = store.get_run("org-a", job.run_id)
    assert len(rr.results) == 2


def test_job_progress_is_not_readable_by_another_org(tmp_path):
    """The progress writers are worker-scoped by design; the read side is not.

    `JobQueue.start_progress`/`record_progress` take no org_id on purpose -- they
    join the `claim_job`/`release_job` family, whose authority is the lease, not
    a tenant claim. What must hold is that no other org can read the result.
    """
    store = Store(str(tmp_path / "progress-tenancy.db"))
    job_id = store.jobs.enqueue("org-a", "t", "p")
    store.jobs.start_progress(job_id, 5)
    store.jobs.record_progress(job_id, "x.case", "failed")

    assert store.jobs.get("org-a", job_id).tests_done == 1
    with pytest.raises(KeyError):
        store.jobs.get("org-b", job_id)


def test_a_job_past_its_time_limit_expires_and_keeps_partial_evidence(tmp_path, monkeypatch):
    """The budget is enforced between tests, so the test already dispatched
    finishes and its result is kept -- an expired job links the evidence that
    exists rather than throwing it away."""
    store = Store(str(tmp_path / "timeout.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    tests = [{**_TEST, "id": f"w.pass.case.{n}"} for n in range(2)]
    store.save_pack("org-a", "pack-1", "Pack One", tests)
    job_id = store.jobs.enqueue("org-a", "worker-target", "pack-1", timeout_seconds=60)

    # Jump the monotonic clock past the budget once the first test lands,
    # rather than sleeping through a real minute.
    original_record_progress = JobQueue.record_progress
    clock = time.monotonic()

    def _record_then_exhaust_budget(self, job_id_, test_id, status):
        original_record_progress(self, job_id_, test_id, status)
        monkeypatch.setattr(time, "monotonic", lambda: clock + 3600)

    monkeypatch.setattr(JobQueue, "record_progress", _record_then_exhaust_budget)

    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "expired"
    assert job.error == "exceeded its time limit"
    assert job.run_id is not None

    run, _ = store.get_run("org-a", job.run_id)
    assert [r.test_id for r in run.results] == ["w.pass.case.0"]


def test_a_job_inside_its_time_limit_finishes_normally(tmp_path):
    """A budget that is never exhausted must not change the outcome."""
    store = Store(str(tmp_path / "in-budget.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    store.save_pack("org-a", "pack-1", "Pack One", [_TEST])
    job_id = store.jobs.enqueue("org-a", "worker-target", "pack-1", timeout_seconds=3600)

    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "done"
    assert job.error is None


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


def test_a_cancel_beats_a_timeout_when_both_fired(tmp_path, monkeypatch):
    """A user who asked for a stop got one. Reporting their cancel as a timeout
    would blame the agent for being slow when it was not."""
    store = Store(str(tmp_path / "both.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    tests = [{**_TEST, "id": f"w.pass.case.{n}"} for n in range(2)]
    store.save_pack("org-a", "pack-1", "Pack One", tests)
    job_id = store.jobs.enqueue("org-a", "worker-target", "pack-1", timeout_seconds=60)

    original_record_progress = JobQueue.record_progress
    clock = time.monotonic()

    def _record_then_both(self, job_id_, test_id, status):
        original_record_progress(self, job_id_, test_id, status)
        self.request_cancel("org-a", job_id_)
        monkeypatch.setattr(time, "monotonic", lambda: clock + 3600)

    monkeypatch.setattr(JobQueue, "record_progress", _record_then_both)

    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "failed"
    assert job.error == "cancelled by user"


def test_a_job_with_no_time_limit_is_unbounded(tmp_path, monkeypatch):
    """None means no limit, so no clock jump can stop it -- that is what every
    job meant before the budget existed."""
    store = Store(str(tmp_path / "unbounded.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    tests = [{**_TEST, "id": f"w.pass.case.{n}"} for n in range(2)]
    store.save_pack("org-a", "pack-1", "Pack One", tests)
    job_id = store.jobs.enqueue("org-a", "worker-target", "pack-1")

    original_record_progress = JobQueue.record_progress
    clock = time.monotonic()

    def _record_then_jump(self, job_id_, test_id, status):
        original_record_progress(self, job_id_, test_id, status)
        monkeypatch.setattr(time, "monotonic", lambda: clock + 86_400)

    monkeypatch.setattr(JobQueue, "record_progress", _record_then_jump)

    work_once(store, "w1")

    job = store.jobs.get("org-a", job_id)
    assert job.state == "done"
    assert store.jobs.get("org-a", job_id).tests_done == 2


def test_a_non_positive_time_limit_is_rejected(tmp_path):
    """Zero is not "no limit": a caller asking for a budget of nothing means
    something, and running forever is the wrong reading of it."""
    store = Store(str(tmp_path / "bad-budget.db"))
    store.save_target("org-a", "worker-target", "Worker Target", _TARGET_CONFIG)
    store.save_pack("org-a", "pack-1", "Pack One", [_TEST])

    for bad in (0, -1):
        with pytest.raises(ValueError, match="timeout_seconds"):
            store.jobs.enqueue("org-a", "worker-target", "pack-1", timeout_seconds=bad)
