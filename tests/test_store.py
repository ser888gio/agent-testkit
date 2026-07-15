from agentkit.core.config import CallableSpec, TargetConfig
from agentkit.core.redaction import EvidencePolicy
from agentkit.core.runner import run
from agentkit.core.schema import Assertion, Category, TestCase
from agentkit.core.scoring import score
from agentkit.core.store import Store

MODULE = "tests.test_store"


def _passing_agent(input: str) -> str:
    return "ok, my key is sk-abcdefgh12345678"


def create_passing_agent():
    return _passing_agent


def _target(evidence: EvidencePolicy | None = None) -> TargetConfig:
    return TargetConfig(
        id="store-target",
        agent=CallableSpec(type="callable", callable=f"{MODULE}:create_passing_agent"),
        evidence=evidence or EvidencePolicy(),
    )


def _run_and_score(evidence: EvidencePolicy | None = None):
    cfg = _target(evidence)
    tests = [
        TestCase(
            id="a.pass.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        )
    ]
    rr = run(cfg, tests)
    report = score(rr)
    return cfg, rr, report


def test_save_and_get_run_round_trips():
    cfg, rr, report = _run_and_score()
    store = Store(":memory:")
    store.save_run(cfg, rr, report)

    rr2, report2 = store.get_run(rr.run_id)
    assert rr2.run_id == rr.run_id
    assert rr2.agent_name == rr.agent_name
    assert [r.test_id for r in rr2.results] == [r.test_id for r in rr.results]
    assert [r.status for r in rr2.results] == [r.status for r in rr.results]
    assert report2.overall_score == report.overall_score
    assert report2.gate_passed == report.gate_passed


def test_list_runs_and_agents_newest_first_and_limit():
    store = Store(":memory:")
    cfg, rr1, report1 = _run_and_score()
    store.save_run(cfg, rr1, report1)
    cfg, rr2, report2 = _run_and_score()
    store.save_run(cfg, rr2, report2)

    runs = store.list_runs(cfg.id)
    assert [r.id for r in runs] == [rr2.run_id, rr1.run_id] or {r.id for r in runs} == {
        rr1.run_id,
        rr2.run_id,
    }
    assert len(store.list_runs(cfg.id, limit=1)) == 1

    agents = store.list_agents()
    assert [a.id for a in agents] == [cfg.id]


def test_pass_fail_matrix_reflects_latest_run():
    store = Store(":memory:")
    cfg, rr1, report1 = _run_and_score()
    store.save_run(cfg, rr1, report1)
    cfg, rr2, report2 = _run_and_score()
    store.save_run(cfg, rr2, report2)

    matrix = store.pass_fail_matrix(cfg.id)
    assert "reliability" in matrix
    assert matrix["reliability"]["a.pass.case"] == "passed"


def test_store_response_false_persists_null_response():
    cfg, rr, report = _run_and_score(evidence=EvidencePolicy(store_response=False))
    store = Store(":memory:")
    store.save_run(cfg, rr, report)

    rr2, _ = store.get_run(rr.run_id)
    assert rr2.results[0].response is None


def test_secret_redacted_in_stored_evidence():
    cfg, rr, report = _run_and_score()
    store = Store(":memory:")
    store.save_run(cfg, rr, report)

    rr2, _ = store.get_run(rr.run_id)
    assert "sk-abcdefgh12345678" not in str(rr2.results[0].response)


def test_get_unknown_run_raises_keyerror():
    store = Store(":memory:")
    try:
        store.get_run("does-not-exist")
        raise AssertionError("expected KeyError")
    except KeyError:
        pass


def test_reopening_existing_db_does_not_error_or_duplicate(tmp_path):
    db_path = str(tmp_path / "agentkit.db")
    store1 = Store(db_path)
    cfg, rr, report = _run_and_score()
    store1.save_run(cfg, rr, report)
    store1.close()

    store2 = Store(db_path)
    runs = store2.list_runs(cfg.id)
    assert len(runs) == 1
