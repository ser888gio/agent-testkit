import threading
import time

import pytest

import agentaudit.worker as worker_module
from agentaudit.core.store import Store
from agentaudit.worker import PermanentJobError, execute_job, main, work_once

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
    job_id = store.enqueue_job(org, "worker-target", "pack-1", **kw)
    return store, job_id


def test_work_once_runs_the_job_and_persists_the_run(tmp_path):
    store, job_id = _store_with_job(tmp_path)

    assert work_once(store, "w1").id == job_id

    job = store.get_job("org-a", job_id)
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
    job_id = store.enqueue_job("org-a", "nope", "also-nope")

    work_once(store, "w1")

    job = store.get_job("org-a", job_id)
    assert job.state == "failed"
    assert "unknown target or pack" in job.error
    assert store.reclaim_jobs() == 0


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
    job_id = store.enqueue_job("org-a", "bad-endpoint", "pack-1")

    with caplog.at_level("WARNING", logger="agentaudit.worker"):
        work_once(store, "w1")

    job = store.get_job("org-a", job_id)
    assert secret not in (job.error or "")
    assert secret not in caplog.text


def test_execute_job_raises_permanent_for_a_foreign_orgs_target(tmp_path):
    store, _ = _store_with_job(tmp_path, org="org-a")
    stolen = store.enqueue_job("org-b", "worker-target", "pack-1")
    job = store.get_job("org-b", stolen)

    with pytest.raises(PermanentJobError):
        execute_job(store, job)


def test_infrastructure_faults_are_left_for_lease_expiry(tmp_path, monkeypatch):
    store, job_id = _store_with_job(tmp_path)
    monkeypatch.setattr(
        "agentaudit.worker.run_tests", lambda *a, **k: (_ for _ in ()).throw(OSError("disk gone"))
    )

    work_once(store, "w1", lease_seconds=-1)

    # Still 'running' and unreleased -- the reclaim sweep owns the retry.
    assert store.get_job("org-a", job_id).state == "running"
    assert store.reclaim_jobs() == 1
    assert store.get_job("org-a", job_id).state == "queued"


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
    job_id = store.enqueue_job("org-a", "boom", "pack-1")

    work_once(store, "w1")

    assert store.get_job("org-a", job_id).state == "done"
    run, _ = store.get_run("org-a", store.get_job("org-a", job_id).run_id)
    assert [r.status.value for r in run.results] == ["error"]
    assert store.reclaim_jobs() == 0


def test_a_worker_run_persists_the_plan_that_selected_its_tests(tmp_path):
    """A hosted run is evidence too: `report --format plan` must not say "no planner"."""
    store, job_id = _store_with_job(tmp_path)

    work_once(store, "w1")

    run_id = store.get_job("org-a", job_id).run_id
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
    real_run = worker_module.run_tests

    def spy(cfg, cases, **kwargs):
        seen.append(kwargs.get("endpoint", "MISSING"))
        return real_run(cfg, cases, **kwargs)

    monkeypatch.setattr(worker_module, "run_tests", spy)
    store, _ = _store_with_job(tmp_path)

    work_once(store, "w1")

    # Probe calls and the graded run alike: every one carries the bound endpoint
    # keyword, so none of them bypassed validate_endpoint above.
    assert seen, "expected the worker to execute something"
    assert "MISSING" not in seen


def test_per_org_cap_stops_one_partner_starving_another(tmp_path):
    store = Store(str(tmp_path / "cap.db"))
    for _ in range(3):
        store.enqueue_job("org-a", "t", "p")
    b_job = store.enqueue_job("org-b", "t", "p")

    claimed = [store.claim_job(f"w{i}", max_per_org=2) for i in range(3)]

    assert [j.org_id for j in claimed] == ["org-a", "org-a", "org-b"]
    assert claimed[2].id == b_job


def test_heartbeat_keeps_a_long_job_from_being_reclaimed(tmp_path, monkeypatch):
    store, job_id = _store_with_job(tmp_path)
    monkeypatch.setattr("agentaudit.worker.run_tests", _slow_run)

    done = threading.Thread(target=work_once, args=(store, "w1"), kwargs={"lease_seconds": 4})
    done.start()
    time.sleep(2.5)
    reclaimed = store.reclaim_jobs()
    done.join(timeout=10)

    assert reclaimed == 0
    assert store.get_job("org-a", job_id).state == "done"


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
        if check.get_job("org-a", job_id).state == "done":
            break
        time.sleep(0.1)
    stop.set()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert check.get_job("org-a", job_id).state == "done"
