import inspect
import sqlite3
from datetime import datetime, timezone

import pytest
from agentkit.core.config import CallableSpec, TargetConfig, load_target_dict
from agentkit.core.loader import LoaderError, load_tests_from_rows
from agentkit.core.redaction import EvidencePolicy
from agentkit.core.runner import run
from agentkit.core.schema import Assertion, Category, TestCase
from agentkit.core.scoring import score
from agentkit.core.store import DEFAULT_ORG, Store

MODULE = "tests.test_store"


def _passing_agent(input: str) -> str:
    return "ok, my key is sk-abcdefgh12345678"


def create_passing_agent():
    return _passing_agent


def _target(
    evidence: EvidencePolicy | None = None, target_id: str = "store-target"
) -> TargetConfig:
    return TargetConfig(
        id=target_id,
        agent=CallableSpec(type="callable", callable=f"{MODULE}:create_passing_agent"),
        evidence=evidence or EvidencePolicy(),
    )


def _run_and_score(
    evidence: EvidencePolicy | None = None,
    *,
    target_id: str = "store-target",
    test_id: str = "a.pass.case",
    passing: bool = True,
    started_at: datetime | None = None,
):
    cfg = _target(evidence, target_id)
    assertion = Assertion(name="status_ok") if passing else Assertion(name="is_valid_json")
    tests = [
        TestCase(
            id=test_id,
            category=Category.reliability,
            input="hi",
            assertions=[assertion],
        )
    ]
    rr = run(cfg, tests)
    if started_at is not None:
        rr.started_at = started_at
        rr.finished_at = started_at
    report = score(rr)
    return cfg, rr, report


def test_save_and_get_run_round_trips():
    cfg, rr, report = _run_and_score()
    store = Store(":memory:")
    store.save_run(DEFAULT_ORG, cfg, rr, report)

    rr2, report2 = store.get_run(DEFAULT_ORG, rr.run_id)
    assert rr2.run_id == rr.run_id
    assert rr2.agent_name == rr.agent_name
    assert [r.test_id for r in rr2.results] == [r.test_id for r in rr.results]
    assert [r.status for r in rr2.results] == [r.status for r in rr.results]
    assert report2.overall_score == report.overall_score
    assert report2.gate_passed == report.gate_passed


def test_list_runs_and_agents_newest_first_and_limit():
    store = Store(":memory:")
    cfg, rr1, report1 = _run_and_score(started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.save_run(DEFAULT_ORG, cfg, rr1, report1)
    cfg, rr2, report2 = _run_and_score(started_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    store.save_run(DEFAULT_ORG, cfg, rr2, report2)

    runs = store.list_runs(DEFAULT_ORG, cfg.id)
    assert [r.id for r in runs] == [rr2.run_id, rr1.run_id]
    assert len(store.list_runs(DEFAULT_ORG, cfg.id, limit=1)) == 1

    agents = store.list_agents(DEFAULT_ORG)
    assert [a.id for a in agents] == [cfg.id]


def test_pass_fail_matrix_reflects_latest_run():
    store = Store(":memory:")
    cfg, rr1, report1 = _run_and_score(
        test_id="old.fail.case",
        passing=False,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    store.save_run(DEFAULT_ORG, cfg, rr1, report1)
    cfg, rr2, report2 = _run_and_score(
        test_id="new.pass.case",
        started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    store.save_run(DEFAULT_ORG, cfg, rr2, report2)

    matrix = store.pass_fail_matrix(DEFAULT_ORG, cfg.id)
    assert matrix == {"reliability": {"new.pass.case": "passed"}}


def test_store_response_false_persists_null_response():
    cfg, rr, report = _run_and_score(evidence=EvidencePolicy(store_response=False))
    store = Store(":memory:")
    store.save_run(DEFAULT_ORG, cfg, rr, report)

    rr2, _ = store.get_run(DEFAULT_ORG, rr.run_id)
    assert rr2.results[0].response is None


def test_secret_redacted_in_stored_evidence():
    cfg, rr, report = _run_and_score()
    store = Store(":memory:")
    store.save_run(DEFAULT_ORG, cfg, rr, report)

    rr2, _ = store.get_run(DEFAULT_ORG, rr.run_id)
    assert "sk-abcdefgh12345678" not in str(rr2.results[0].response)


def test_get_unknown_run_raises_keyerror():
    store = Store(":memory:")
    try:
        store.get_run(DEFAULT_ORG, "does-not-exist")
        raise AssertionError("expected KeyError")
    except KeyError:
        pass


def test_reads_are_scoped_to_the_calling_org():
    store = Store(":memory:")
    cfg_a, rr_a, report_a = _run_and_score(target_id="agent-a", test_id="orga.pass.case")
    store.save_run("org-a", cfg_a, rr_a, report_a)
    cfg_b, rr_b, report_b = _run_and_score(
        target_id="agent-b", test_id="orgb.fail.case", passing=False
    )
    store.save_run("org-b", cfg_b, rr_b, report_b)

    assert [r.id for r in store.list_runs("org-a")] == [rr_a.run_id]
    assert [r.id for r in store.list_runs("org-b")] == [rr_b.run_id]
    assert [r.id for r in store.list_runs("org-a", cfg_a.id)] == [rr_a.run_id]
    assert store.run_count("org-a", cfg_a.id) == 1
    assert store.run_count("org-a", cfg_b.id) == 0
    assert [(a.org_id, a.id) for a in store.list_agents("org-a")] == [("org-a", "agent-a")]
    assert [(a.org_id, a.id) for a in store.list_agents("org-b")] == [("org-b", "agent-b")]
    assert [t["test_id"] for t in store.list_tests("org-a")] == ["orga.pass.case"]
    assert [t["test_id"] for t in store.list_tests("org-b")] == ["orgb.fail.case"]
    assert store.pass_fail_matrix("org-a", cfg_a.id) == {
        "reliability": {"orga.pass.case": "passed"}
    }
    assert store.pass_fail_matrix("org-b", cfg_b.id) == {
        "reliability": {"orgb.fail.case": "failed"}
    }
    assert store.list_runs("org-c") == []
    assert store.list_agents("org-c") == []
    assert store.list_tests("org-c") == []
    assert store.pass_fail_matrix("org-c", cfg_a.id) == {}


def test_tenant_constraints_reject_mismatched_result_owner():
    store = Store(":memory:")
    cfg, rr, report = _run_and_score()
    store.save_run("org-a", cfg, rr, report)
    store._conn.execute(  # noqa: SLF001 - verify the database boundary directly
        "INSERT INTO orgs (id, name, created_at) VALUES ('org-b', 'B', 'now')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(  # noqa: SLF001 - intentionally violate tenant lineage
            "UPDATE test_results SET org_id = 'org-b' WHERE run_id = ?", (rr.run_id,)
        )


def test_reads_fail_closed_for_inconsistent_tenant_markers():
    store = Store(":memory:")
    cfg, rr, report = _run_and_score()
    store.save_run("org-a", cfg, rr, report)
    store._conn.commit()  # noqa: SLF001 - create legacy/corrupt data for a read-boundary test
    store._conn.execute("PRAGMA foreign_keys = OFF")  # noqa: SLF001
    store._conn.execute(  # noqa: SLF001
        "UPDATE test_results SET org_id = 'org-b' WHERE run_id = ?", (rr.run_id,)
    )
    store._conn.commit()  # noqa: SLF001
    store._conn.execute("PRAGMA foreign_keys = ON")  # noqa: SLF001

    assert store.list_tests("org-b") == []
    assert store.pass_fail_matrix("org-a", cfg.id) == {}


def test_get_run_of_another_org_raises_keyerror():
    store = Store(":memory:")
    cfg, rr, report = _run_and_score()
    store.save_run("org-a", cfg, rr, report)

    store.get_run("org-a", rr.run_id)  # sanity: it does exist
    try:
        store.get_run("org-b", rr.run_id)
        raise AssertionError("expected KeyError")
    except KeyError:
        pass


def test_no_public_method_defaults_org_id():
    for name in (
        "save_run",
        "list_agents",
        "list_tests",
        "list_runs",
        "run_count",
        "get_run",
        "pass_fail_matrix",
        "save_target",
        "get_target",
        "list_targets",
        "save_pack",
        "get_pack_tests",
        "list_packs",
    ):
        parameters = list(inspect.signature(getattr(Store, name)).parameters.values())
        assert [parameter.name for parameter in parameters[:2]] == ["self", "org_id"], name
        param = parameters[1]
        assert param.default is inspect.Parameter.empty, name


_TARGET_CONFIG = {
    "id": "stored-agent",
    "agent": {"type": "http", "endpoint": "https://example.test/agent"},
}
_PACK_TEST = {
    "id": "pack.t1",
    "input": "hello",
    "category": "reliability",
    "assertions": [{"name": "status_ok"}],
}


def test_target_row_round_trips_through_load_target_dict():
    store = Store(":memory:")
    store.save_target("org-a", "stored-agent", "Stored", _TARGET_CONFIG)

    from_row = load_target_dict(store.get_target("org-a", "stored-agent"))
    assert from_row == load_target_dict(_TARGET_CONFIG)
    assert [t.id for t in store.list_targets("org-a")] == ["stored-agent"]


def test_pack_rows_round_trip_through_load_tests_from_rows():
    store = Store(":memory:")
    store.save_pack("org-a", "p1", "Pack One", [_PACK_TEST])

    cases = load_tests_from_rows(store.get_pack_tests("org-a", "p1"))
    assert [c.id for c in cases] == ["pack.t1"]
    assert [(p.id, p.test_count) for p in store.list_packs("org-a")] == [("p1", 1)]


def test_save_pack_replaces_previous_tests():
    store = Store(":memory:")
    store.save_pack("org-a", "p1", "Pack One", [_PACK_TEST, dict(_PACK_TEST, id="pack.t2")])
    store.save_pack("org-a", "p1", "Pack One", [_PACK_TEST])

    assert [t["id"] for t in store.get_pack_tests("org-a", "p1")] == ["pack.t1"]


def test_bad_assertion_in_a_row_raises_loadererror():
    store = Store(":memory:")
    bad = dict(_PACK_TEST, assertions=[{"name": "no_such_assertion", "value": "x"}])
    store.save_pack("org-a", "p1", "Pack One", [bad])

    with pytest.raises(LoaderError):
        load_tests_from_rows(store.get_pack_tests("org-a", "p1"))


def test_targets_and_packs_are_scoped_to_the_calling_org():
    store = Store(":memory:")
    store.save_target("org-a", "stored-agent", "Stored", _TARGET_CONFIG)
    store.save_pack("org-a", "p1", "Pack One", [_PACK_TEST])

    assert store.list_targets("org-b") == []
    assert store.list_packs("org-b") == []
    with pytest.raises(KeyError):
        store.get_target("org-b", "stored-agent")
    with pytest.raises(KeyError):
        store.get_pack_tests("org-b", "p1")


def test_reopening_existing_db_does_not_error_or_duplicate(tmp_path):
    db_path = str(tmp_path / "agentkit.db")
    store1 = Store(db_path)
    cfg, rr, report = _run_and_score()
    store1.save_run(DEFAULT_ORG, cfg, rr, report)
    store1.close()

    store2 = Store(db_path)
    runs = store2.list_runs(DEFAULT_ORG, cfg.id)
    assert len(runs) == 1
