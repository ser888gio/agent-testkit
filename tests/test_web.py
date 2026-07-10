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


def test_test_detail_shows_redacted_response_assertions_latency(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}/tests/b.fail.case")
    assert resp.status_code == 200
    assert "sk-abcdefgh12345678" not in resp.text
    assert "not_contains" in resp.text
    assert "ms" in resp.text


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


def test_agent_detail_links_matrix_tests_to_latest_run(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/agents/web-target")
    assert resp.status_code == 200
    assert "b.fail.case" in resp.text
    # matrix test id links through to its test detail page in the latest run
    assert f"/runs/{rr.run_id}/tests/b.fail.case" in resp.text


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
