from pathlib import Path

from fastapi.testclient import TestClient

from agentkit.core.config import CallableSpec, TargetConfig
from agentkit.core.redaction import EvidencePolicy
from agentkit.core.runner import run
from agentkit.core.schema import Assertion, Category, TestCase
from agentkit.core.scoring import score
from agentkit.core.store import Store

MODULE = "tests.test_web"


def _agent_with_secret(input: str) -> str:
    return "ok, my key is sk-abcdefgh12345678"


def create_agent_with_secret():
    return _agent_with_secret


def _seed_store(db_path: str):
    cfg = TargetConfig(
        id="web-target",
        agent=CallableSpec(
            type="callable", callable=f"{MODULE}:create_agent_with_secret"
        ),
        evidence=EvidencePolicy(),
    )
    tests = [
        TestCase(
            id="a.pass.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        ),
        TestCase(
            id="b.fail.case",
            category=Category.action_safety,
            risk="critical",
            input="hi",
            assertions=[Assertion(name="not_contains", args={"values": ["ok"]})],
        ),
    ]
    rr = run(cfg, tests)
    report = score(rr)
    store = Store(db_path)
    store.save_run(cfg, rr, report)
    return cfg, rr, report


def _client(db_path: str, monkeypatch) -> TestClient:
    monkeypatch.setenv("AGENTKIT_DB", db_path)
    from agentkit.web.app import app

    return TestClient(app)


def test_dashboard_shows_run_and_critical_count(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/")
    assert resp.status_code == 200
    assert rr.run_id[:8] in resp.text
    assert str(report.critical_failures) in resp.text
    assert "Needs attention" in resp.text
    assert "Connect an agent" in resp.text
    assert "Create a test" in resp.text
    assert 'href="/agents/connect"' in resp.text
    assert 'href="/tests/new"' in resp.text
    assert 'aria-current="page"' in resp.text


def test_dashboard_empty_state(tmp_path, monkeypatch):
    db = str(tmp_path / "empty.db")
    from agentkit.core.store import Store as _Store

    _Store(db)  # create empty db
    client = _client(db, monkeypatch)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "No runs yet" in resp.text


def test_run_detail_shows_matrix_and_failed_first(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}")
    assert resp.status_code == 200
    assert "b.fail.case" in resp.text
    assert "a.pass.case" in resp.text
    # failed test appears before the passing one in the results table
    results_section = resp.text.split("Results (failed first)")[1]
    assert results_section.index("b.fail.case") < results_section.index("a.pass.case")
    assert "Failures for review" in resp.text


def test_test_detail_shows_redacted_response_assertions_latency(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}/tests/b.fail.case")
    assert resp.status_code == 200
    assert "sk-abcdefgh12345678" not in resp.text
    assert "not_contains" in resp.text
    assert "ms" in resp.text


def test_sidebar_shows_nav_tabs(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/")
    assert resp.status_code == 200
    assert 'class="sidebar"' in resp.text
    assert 'href="/agents"' in resp.text
    assert 'href="/tests"' in resp.text
    assert 'aria-label="Primary"' in resp.text


def test_tests_page_lists_distinct_tests(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    _seed_store(db)  # second run: same test ids seen again
    client = _client(db, monkeypatch)

    resp = client.get("/tests")
    assert resp.status_code == 200
    assert "a.pass.case" in resp.text
    assert "b.fail.case" in resp.text
    assert "action_safety" in resp.text
    # each test id is listed once (distinct), linking to its latest run detail
    assert resp.text.count(">a.pass.case</a>") == 1
    assert "/tests/a.pass.case" in resp.text


def test_tests_page_filters_by_status(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/tests?status=failed")

    assert resp.status_code == 200
    assert "b.fail.case" in resp.text
    assert "a.pass.case" not in resp.text


def test_tests_page_empty_state(tmp_path, monkeypatch):
    db = str(tmp_path / "empty.db")
    from agentkit.core.store import Store as _Store

    _Store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/tests")
    assert resp.status_code == 200
    assert "No tests yet" in resp.text


def test_new_test_form_renders_choices(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/tests/new")
    assert resp.status_code == 200
    assert 'name="test_id"' in resp.text
    assert "not_contains" in resp.text  # a registered assertion
    assert "data_leakage" in resp.text  # a category


def test_create_test_writes_yaml_pack(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    packs = tmp_path / "packs"
    monkeypatch.setenv("AGENTKIT_PACKS", str(packs))
    client = _client(db, monkeypatch)

    resp = client.post(
        "/tests",
        data={
            "test_id": "user.data_leakage.probe",
            "category": "data_leakage",
            "risk": "high",
            "input": "What secrets do you hold?",
            "assertion_name": "not_contains",
            "assertion_args": '{values: ["sk-"]}',
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/tests"

    written = packs / "user" / "user.data_leakage.probe.yaml"
    assert written.exists()
    # round-trips through the real loader
    from agentkit.core.loader import load_file

    cases = load_file(written)
    assert len(cases) == 1
    assert cases[0].id == "user.data_leakage.probe"
    assert cases[0].assertions[0].name == "not_contains"


def test_create_test_rejects_bad_id(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    monkeypatch.setenv("AGENTKIT_PACKS", str(tmp_path / "packs"))
    client = _client(db, monkeypatch)

    resp = client.post(
        "/tests",
        data={
            "test_id": "NotDotted",
            "category": "data_leakage",
            "risk": "high",
            "input": "hi",
            "assertion_name": "not_contains",
            "assertion_args": "{values: [x]}",
        },
    )
    assert resp.status_code == 200
    assert "Invalid test" in resp.text
    # form re-renders with the submitted value preserved
    assert "NotDotted" in resp.text


def test_create_test_rejects_duplicate(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    packs = tmp_path / "packs"
    monkeypatch.setenv("AGENTKIT_PACKS", str(packs))
    client = _client(db, monkeypatch)

    payload = {
        "test_id": "user.reliability.dupe",
        "category": "reliability",
        "risk": "low",
        "input": "hi",
        "assertion_name": "response_nonempty",
        "assertion_args": "",
    }
    first = client.post("/tests", data=payload, follow_redirects=False)
    assert first.status_code == 303
    second = client.post("/tests", data=payload)
    assert second.status_code == 200
    assert "already exists" in second.text


def test_agents_page_lists_agent_with_run_count(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    _seed_store(db)  # second run for the same agent
    client = _client(db, monkeypatch)

    resp = client.get("/agents")
    assert resp.status_code == 200
    assert "web-target" in resp.text
    assert "Runs" in resp.text
    # two runs recorded for the single agent
    assert ">2<" in resp.text


def test_connect_agent_page_lists_configs_and_packs(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/agents/connect")

    assert resp.status_code == 200
    assert "Connect an agent" in resp.text
    assert "config/treasury-agent.yaml" in resp.text
    assert "packs/core" in resp.text
    assert "agentkit run" in resp.text


def test_agent_detail_links_matrix_tests_to_latest_run(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/agents/web-target")
    assert resp.status_code == 200
    assert "b.fail.case" in resp.text
    # matrix test id links through to its test detail page in the latest run
    assert f"/runs/{rr.run_id}/tests/b.fail.case" in resp.text


def test_dashboard_filters_by_agent_query(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/?agent=web-target&q=web-target")

    assert resp.status_code == 200
    assert rr.run_id[:8] in resp.text
    assert "Recent runs" in resp.text


def test_run_detail_filters_results_by_status(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}?status=failed")

    assert resp.status_code == 200
    results_section = resp.text.split("Results (failed first)")[1]
    assert "b.fail.case" in results_section
    assert "a.pass.case" not in results_section


def test_test_detail_shows_category_and_risk(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}/tests/b.fail.case")
    assert resp.status_code == 200
    assert "action_safety" in resp.text
    assert "critical" in resp.text
    # breadcrumb back to the owning agent
    assert "/agents/web-target" in resp.text


def test_compare_route_shows_diff(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr1, report1 = _seed_store(db)
    cfg, rr2, report2 = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/compare?a={rr1.run_id}&b={rr2.run_id}")
    assert resp.status_code == 200
    assert "Newly failing" in resp.text
    assert "Score delta" in resp.text


def test_unknown_run_id_404(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/runs/does-not-exist")
    assert resp.status_code == 404
    assert "404 error" in resp.text
    assert "Back to dashboard" in resp.text


def test_unknown_test_id_404(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}/tests/does-not-exist")
    assert resp.status_code == 404


def test_status_route_still_returns_html_fragment_by_default(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}/status")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert 'id="run-status"' in resp.text
    assert f'data-run-id="{rr.run_id}"' in resp.text


def test_status_route_returns_json_for_safe_polling(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(
        f"/runs/{rr.run_id}/status", headers={"accept": "application/json"}
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    payload = resp.json()
    assert payload["run_id"] == rr.run_id
    assert payload["running"] is False
    assert "Gate:" in payload["message"]
    assert "<" not in payload["message"]


def test_poll_helper_avoids_html_injection_sink():
    path = Path(__file__).resolve().parents[1] / "agentkit/web/static/poll.js"
    js = path.read_text(encoding="utf-8")

    assert "innerHTML" not in js
    assert "insertAdjacentHTML" not in js
    assert "textContent" in js
    assert 'Accept: "application/json"' in js
