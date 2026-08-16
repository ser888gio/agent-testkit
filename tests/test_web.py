from pathlib import Path

import pytest
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from agentaudit.core.config import CallableSpec, TargetConfig
from agentaudit.core.profile import AgentProfile, ExcludedTest, HarnessPlan, SelectedTest
from agentaudit.core.redaction import EvidencePolicy
from agentaudit.core.runner import run
from agentaudit.core.schema import Assertion, Category
from agentaudit.core.schema import TestCase as SchemaTestCase
from agentaudit.core.scoring import score
from agentaudit.core.store import DEFAULT_ORG, Store

MODULE = "tests.test_web"


@pytest.fixture(autouse=True)
def explicit_dev_auth(monkeypatch):
    monkeypatch.setenv("AGENTAUDIT_AUTH_MODE", "dev")


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
        SchemaTestCase(
            id="a.pass.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        ),
        SchemaTestCase(
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
    store.save_run(DEFAULT_ORG, cfg, rr, report)
    return cfg, rr, report


def _seed_passing_store(db_path: str):
    cfg = TargetConfig(
        id="clean-target",
        agent=CallableSpec(
            type="callable", callable=f"{MODULE}:create_agent_with_secret"
        ),
        evidence=EvidencePolicy(),
    )
    tests = [
        SchemaTestCase(
            id="clean.pass.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        ),
    ]
    rr = run(cfg, tests)
    report = score(rr)
    store = Store(db_path)
    store.save_run(DEFAULT_ORG, cfg, rr, report)
    return cfg, rr, report


def _client(db_path: str, monkeypatch) -> TestClient:
    monkeypatch.setenv("AGENTAUDIT_DB", db_path)
    from agentaudit.web.app import app

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
    assert "Apply Filters" not in resp.text


def test_dashboard_empty_state(tmp_path, monkeypatch):
    db = str(tmp_path / "empty.db")
    from agentaudit.core.store import Store as _Store

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
    assert f"/runs/{rr.run_id}/harness" in resp.text


def test_run_harness_shows_findings_skills_context_summary(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}/harness")

    assert resp.status_code == 200
    assert "Test Harness" in resp.text
    assert "Workflow / History" in resp.text
    assert "Harness Environment" in resp.text
    assert "Memory &amp; Context" in resp.text
    assert "No memory/context checks were included" in resp.text
    assert "Skills" in resp.text
    assert "Action Safety" in resp.text
    assert "b.fail.case" in resp.text
    assert "not_contains" in resp.text
    assert f'data-poll-url="/runs/{rr.run_id}/status"' in resp.text
    assert rr.run_id in resp.text
    assert (
        'href="/harness" data-testid="nav-harness" '
        'class="active" aria-current="page"' in resp.text
    )


def test_harness_nav_redirects_to_latest_run(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _cfg, rr, _report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/harness", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == f"/runs/{rr.run_id}/harness"


def test_harness_nav_has_empty_state_without_runs(tmp_path, monkeypatch):
    db = str(tmp_path / "empty.db")
    Store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/harness")

    assert resp.status_code == 200
    assert "No harness data yet" in resp.text
    assert (
        'href="/harness" data-testid="nav-harness" '
        'class="active" aria-current="page"' in resp.text
    )


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
    assert 'href="/harness"' in resp.text
    assert 'href="/"' in resp.text
    assert 'href="/agents"' in resp.text
    assert 'href="/tests"' in resp.text
    assert 'href="/settings"' in resp.text
    assert 'aria-label="Primary"' in resp.text
    assert 'class="nav-icon"' in resp.text


def test_runs_route_shows_dashboard_table(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/runs")

    assert resp.status_code == 200
    assert "Recent runs" in resp.text
    assert rr.run_id[:8] in resp.text
    assert 'href="/" data-testid="nav-runs" class="active" aria-current="page"' in resp.text


def test_settings_page_shows_safe_runtime_config(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/settings")

    assert resp.status_code == 200
    assert "Settings" in resp.text
    assert "Storage" in resp.text
    assert "Run Inputs" in resp.text
    assert "Security" in resp.text
    assert db in resp.text
    assert "AGENTAUDIT_OIDC" not in resp.text
    assert (
        'href="/settings" data-testid="nav-settings" '
        'class="active" aria-current="page"' in resp.text
    )


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
    assert "Apply Filters" not in resp.text


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
    from agentaudit.core.store import Store as _Store

    _Store(db)
    # The library lists shipped packs too, so "empty" means no packs either.
    empty_packs = tmp_path / "packs"
    empty_packs.mkdir()
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(empty_packs))
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


def test_create_test_stores_db_row(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    packs = tmp_path / "packs"
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(packs))
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

    # Stored as an org-scoped DB row, and nothing was written to the packs dir.
    assert not packs.exists()
    rows = Store(db).get_pack_tests(DEFAULT_ORG, "user")
    assert len(rows) == 1
    # round-trips through the real loader
    from agentaudit.core.loader import load_tests_from_rows

    cases = load_tests_from_rows(rows)
    assert cases[0].id == "user.data_leakage.probe"
    assert cases[0].assertions[0].name == "not_contains"


def test_create_test_rejects_bad_id(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(tmp_path / "packs"))
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
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(packs))
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
    assert "duplicate test id" in second.text


def _create_test_payload(**overrides):
    return {
        "test_id": "user.reliability.case",
        "category": "reliability",
        "risk": "low",
        "input": "hi",
        "assertion_name": "response_nonempty",
        "assertion_args": "",
        **overrides,
    }


def test_create_test_rejects_malformed_yaml_args(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(tmp_path / "packs"))
    client = _client(db, monkeypatch)

    resp = client.post(
        "/tests",
        data=_create_test_payload(assertion_args="{values: [unclosed"),
    )
    assert resp.status_code == 200
    assert "not valid YAML" in resp.text


def test_create_test_rejects_non_mapping_args(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(tmp_path / "packs"))
    client = _client(db, monkeypatch)

    resp = client.post(
        "/tests",
        data=_create_test_payload(assertion_args="- just\n- a list"),
    )
    assert resp.status_code == 200
    assert "must be a YAML mapping" in resp.text


def test_create_test_rejects_unknown_assertion(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(tmp_path / "packs"))
    client = _client(db, monkeypatch)

    resp = client.post(
        "/tests",
        data=_create_test_payload(assertion_name="does_not_exist"),
    )
    assert resp.status_code == 200
    assert "Unknown assertion" in resp.text


def test_agents_page_lists_agent_with_run_count(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    _seed_store(db)  # second run for the same agent
    client = _client(db, monkeypatch)

    resp = client.get("/agents")
    assert resp.status_code == 200
    assert "web-target" in resp.text
    assert "Runs" in resp.text
    assert "Add Agent" in resp.text
    assert 'href="/agents/connect"' in resp.text
    # two runs recorded for the single agent
    assert ">2<" in resp.text


def test_agents_page_empty_state_links_add_agent(tmp_path, monkeypatch):
    db = str(tmp_path / "empty.db")
    from agentaudit.core.store import Store as _Store

    _Store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/agents")

    assert resp.status_code == 200
    assert "No agents yet" in resp.text
    assert "Add Agent" in resp.text
    assert 'href="/agents/connect"' in resp.text


def test_connect_agent_page_lists_configs_and_packs(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get("/agents/connect")

    assert resp.status_code == 200
    assert "Connect an agent" in resp.text
    assert "config/treasury-agent.yaml" in resp.text
    assert "packs/core" in resp.text
    assert "agentaudit run" in resp.text


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


def test_dashboard_status_filter_uses_result_summary(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _, failed_run, _ = _seed_store(db)
    _, passed_run, _ = _seed_passing_store(db)
    client = _client(db, monkeypatch)

    failed_resp = client.get("/?status=failed")

    assert failed_resp.status_code == 200
    assert failed_run.run_id[:8] in failed_resp.text
    assert passed_run.run_id[:8] not in failed_resp.text

    passed_resp = client.get("/?status=passed")

    assert passed_resp.status_code == 200
    assert passed_run.run_id[:8] in passed_resp.text
    assert failed_run.run_id[:8] not in passed_resp.text


def test_run_detail_filters_results_by_status(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}?status=failed")

    assert resp.status_code == 200
    results_section = resp.text.split("Results (failed first)")[1]
    assert "b.fail.case" in results_section
    assert "a.pass.case" not in results_section
    assert "Apply Filters" not in resp.text


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


def test_compare_with_unknown_run_404(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/compare?a={rr.run_id}&b=does-not-exist")
    assert resp.status_code == 404


def test_data_testid_hooks_present(tmp_path, monkeypatch):
    """UI automation anchors on data-testid, not display copy. Keep them stable."""
    db = str(tmp_path / "web.db")
    cfg, rr, report = _seed_store(db)
    client = _client(db, monkeypatch)

    home = client.get("/").text
    for hook in (
        "nav-harness",
        "nav-runs",
        "nav-agents",
        "nav-tests",
        "nav-settings",
        "action-connect-agent",
        "action-create-test",
        "stat-runs",
        "run-row",
    ):
        assert f'data-testid="{hook}"' in home, hook

    connect = client.get("/agents/connect").text
    assert 'data-testid="connect-form"' in connect
    assert 'data-testid="connect-submit"' in connect

    new_test = client.get("/tests/new").text
    assert 'data-testid="test-form"' in new_test
    assert 'data-testid="test-submit"' in new_test

    detail = client.get(f"/runs/{rr.run_id}").text
    assert 'data-testid="open-harness"' in detail

    harness = client.get(f"/runs/{rr.run_id}/harness").text
    assert 'data-testid="stat-pass-rate"' in harness
    assert 'data-testid="stat-critical-findings"' in harness


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
    import agentaudit.web as web_pkg

    path = Path(web_pkg.__file__).resolve().parent / "static" / "poll.js"
    js = path.read_text(encoding="utf-8")

    assert "innerHTML" not in js
    assert "insertAdjacentHTML" not in js
    assert "textContent" in js
    assert 'Accept: "application/json"' in js
    assert "requestSubmit" in js
    assert "setTimeout(submit, 350)" in js


# --- T8: every route is authenticated and org-scoped -----------------------


def _oidc_env(monkeypatch):
    """Turn on auth without standing up Keycloak; no token will ever verify."""
    monkeypatch.setenv("AGENTAUDIT_AUTH_MODE", "oidc")
    monkeypatch.setenv("AGENTAUDIT_OIDC_JWKS_URL", "https://kc.test/certs")
    monkeypatch.setenv("AGENTAUDIT_OIDC_ISSUER", "https://kc.test/realms/agentaudit")
    monkeypatch.setenv("AGENTAUDIT_OIDC_AUDIENCE", "agentaudit-api")
    monkeypatch.setenv("AGENTAUDIT_OIDC_CLIENT_ID", "agentaudit-web")
    monkeypatch.setenv("AGENTAUDIT_OIDC_REDIRECT_URI", "https://agentaudit.test/auth/callback")


def _concrete_paths() -> list[tuple[str, str]]:
    """Every app route, with path params filled in. Static mount excluded."""
    from agentaudit.web.app import app

    out = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if (
            not path.startswith("/")
            or path.startswith("/static")
            or path in {"/login", "/auth/callback", "/logout"}
        ):
            continue
        for method in methods & {"GET", "POST"}:
            filled = (
                path.replace("{run_id}", "some-run")
                .replace("{test_id}", "some-test")
                .replace("{agent_id:path}", "some-agent")
            )
            out.append((method, filled))
    return out


def test_every_route_requires_a_token(tmp_path, monkeypatch):
    """A new route that forgets `current_principal` fails here."""
    monkeypatch.setenv("AGENTAUDIT_DB", str(tmp_path / "web.db"))
    _oidc_env(monkeypatch)
    from agentaudit.web.app import app

    client = TestClient(app)
    paths = _concrete_paths()
    assert paths, "route table came back empty; the introspection is wrong"

    unprotected = []
    for method, path in paths:
        resp = client.request(method, path, params={"a": "x", "b": "y",
                                                    "target": "t", "packs": "p"},
                              headers={"Accept": "application/json"})
        if resp.status_code != 401:
            unprotected.append((method, path, resp.status_code))
    assert not unprotected


def test_browser_request_starts_code_pkce_login(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTAUDIT_DB", str(tmp_path / "web.db"))
    _oidc_env(monkeypatch)
    from agentaudit.web.app import app

    client = TestClient(app)
    response = client.get("/runs", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")

    login = client.get(response.headers["location"], follow_redirects=False)
    assert login.status_code == 302
    assert login.headers["location"].startswith(
        "https://kc.test/realms/agentaudit/protocol/openid-connect/auth?"
    )
    assert "code_challenge_method=S256" in login.headers["location"]
    assert "agentaudit_login_state=" in login.headers["set-cookie"]


def test_viewer_cannot_create_test(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    Store(db)
    monkeypatch.setenv("AGENTAUDIT_DB", db)
    from agentaudit.web import app as web_app
    from agentaudit.web.auth import Principal

    web_app.app.dependency_overrides[web_app.current_principal] = lambda: Principal(
        DEFAULT_ORG, "viewer", "viewer@example.test", frozenset({"viewer"})
    )
    try:
        response = TestClient(web_app.app).post(
            "/tests",
            data={
                "test_id": "viewer.forbidden",
                "category": "reliability",
                "risk": "low",
                "input": "hi",
                "assertion_name": "response_nonempty",
                "assertion_args": "",
            },
        )
    finally:
        web_app.app.dependency_overrides.clear()
    assert response.status_code == 403
    assert Store(db).list_authored_tests(DEFAULT_ORG) == []


def test_session_mutation_requires_csrf_token(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    Store(db)
    monkeypatch.setenv("AGENTAUDIT_DB", db)
    from agentaudit.web import app as web_app
    from agentaudit.web.auth import Principal

    web_app.app.dependency_overrides[web_app.current_principal] = lambda: Principal(
        DEFAULT_ORG,
        "admin",
        "admin@example.test",
        frozenset({"admin"}),
        auth_method="session",
        csrf_token="expected-token",
    )
    try:
        response = TestClient(web_app.app).post(
            "/tests",
            data={
                "test_id": "csrf.forbidden",
                "category": "reliability",
                "risk": "low",
                "input": "hi",
                "assertion_name": "response_nonempty",
                "assertion_args": "",
            },
        )
    finally:
        web_app.app.dependency_overrides.clear()
    assert response.status_code == 403
    assert Store(db).list_authored_tests(DEFAULT_ORG) == []


def test_session_mutation_accepts_matching_csrf_token(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    Store(db)
    monkeypatch.setenv("AGENTAUDIT_DB", db)
    from agentaudit.web import app as web_app
    from agentaudit.web.auth import Principal

    web_app.app.dependency_overrides[web_app.current_principal] = lambda: Principal(
        DEFAULT_ORG,
        "admin",
        "admin@example.test",
        frozenset({"admin"}),
        auth_method="session",
        csrf_token="expected-token",
    )
    try:
        response = TestClient(web_app.app).post(
            "/tests",
            data={
                "csrf_token": "expected-token",
                "test_id": "csrf.allowed",
                "category": "reliability",
                "risk": "low",
                "input": "hi",
                "assertion_name": "response_nonempty",
                "assertion_args": "",
            },
            follow_redirects=False,
        )
    finally:
        web_app.app.dependency_overrides.clear()
    assert response.status_code == 303
    assert Store(db).list_authored_tests(DEFAULT_ORG)[0]["test_id"] == "csrf.allowed"


def test_run_of_another_org_is_404_not_403(tmp_path, monkeypatch):
    """Org B must not learn that org A's run id exists."""
    db = str(tmp_path / "web.db")
    _cfg, rr, _report = _seed_store(db)
    monkeypatch.setenv("AGENTAUDIT_DB", db)

    from agentaudit.web import app as web_app
    from agentaudit.web.auth import Principal

    client = TestClient(web_app.app)
    # The run was seeded under DEFAULT_ORG; the dev principal is that org.
    assert client.get(f"/runs/{rr.run_id}").status_code == 200

    web_app.app.dependency_overrides[web_app.current_principal] = (
        lambda: Principal("other-org", "sub-b", "b@other.test", frozenset({"admin"}))
    )
    try:
        resp = client.get(f"/runs/{rr.run_id}")
    finally:
        web_app.app.dependency_overrides.clear()
    assert resp.status_code == 404


def test_runs_of_another_org_are_not_listed(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    monkeypatch.setenv("AGENTAUDIT_DB", db)

    from agentaudit.web import app as web_app
    from agentaudit.web.auth import Principal

    client = TestClient(web_app.app)
    assert "web-target" in client.get("/runs").text

    web_app.app.dependency_overrides[web_app.current_principal] = (
        lambda: Principal("other-org", "sub-b", "b@other.test", frozenset({"admin"}))
    )
    try:
        for path in ("/runs", "/agents", "/tests"):
            assert "web-target" not in client.get(path).text, path
    finally:
        web_app.app.dependency_overrides.clear()


def _seed_attributed_store(db: str) -> str:
    """One CLI-launched run (no principal) plus one launched by a human."""
    cfg, _rr, _report = _seed_store(db)
    from agentaudit.core.runner import run as run_tests

    rr2 = run_tests(cfg, [])
    Store(db).save_run(
        DEFAULT_ORG, cfg, rr2, score(rr2),
        created_by="kc-sub-1", created_by_email="launcher@acme.test",
    )
    return rr2.run_id


def test_run_records_who_launched_it(tmp_path):
    db = str(tmp_path / "attr.db")
    run_id = _seed_attributed_store(db)
    row = next(r for r in Store(db).list_runs(DEFAULT_ORG) if r.id == run_id)
    assert row.created_by == "kc-sub-1"
    assert row.created_by_email == "launcher@acme.test"


def test_runs_page_shows_who_launched_each_run(tmp_path, monkeypatch):
    db = str(tmp_path / "attr.db")
    _seed_attributed_store(db)
    monkeypatch.setenv("AGENTAUDIT_DB", db)
    from agentaudit.web.app import app

    body = TestClient(app).get("/runs").text
    assert "launcher@acme.test" in body
    assert "CLI" in body  # the seeded run has no principal


def test_cli_run_has_no_attribution(tmp_path):
    """The CLI has no human principal; attribution is null, not invented."""
    db = str(tmp_path / "cli.db")
    _cfg, rr, _report = _seed_store(db)
    row = next(r for r in Store(db).list_runs(DEFAULT_ORG) if r.id == rr.run_id)
    assert row.created_by is None
    assert row.created_by_email is None


# --- T9: authored tests are org-scoped DB rows, never shared files ---------


def test_authored_test_is_invisible_to_another_org(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    packs = tmp_path / "packs"
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(packs))
    monkeypatch.setenv("AGENTAUDIT_DB", db)

    from agentaudit.web import app as web_app
    from agentaudit.web.auth import Principal

    client = TestClient(web_app.app)
    payload = {
        "test_id": "orga.secret.probe",
        "category": "data_leakage",
        "risk": "high",
        "input": "leak something",
        "assertion_name": "response_nonempty",
        "assertion_args": "",
    }
    assert client.post("/tests", data=payload, follow_redirects=False).status_code == 303
    assert "orga.secret.probe" in client.get("/tests").text

    web_app.app.dependency_overrides[web_app.current_principal] = (
        lambda: Principal("org-b", "sub-b", "b@other.test", frozenset({"admin"}))
    )
    try:
        assert "orga.secret.probe" not in client.get("/tests").text
        # Org B may reuse the id without colliding with org A's row.
        assert client.post(
            "/tests", data=payload, follow_redirects=False
        ).status_code == 303
    finally:
        web_app.app.dependency_overrides.clear()

    assert Store(db).get_pack_tests("org-b", "user")[0]["id"] == "orga.secret.probe"
    assert len(Store(db).get_pack_tests(DEFAULT_ORG, "user")) == 1
    assert not packs.exists()


def test_no_code_path_writes_to_packs_user_dir():
    """The filesystem write is gone, not merely bypassed."""
    source = Path("frontend/agentaudit/web/app.py").read_text(encoding="utf-8")
    assert "write_text" not in source
    assert "mkdir" not in source


def test_authored_test_shows_before_it_has_ever_run(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    Store(db)
    monkeypatch.setenv("AGENTAUDIT_DB", db)
    from agentaudit.web.app import app

    client = TestClient(app)
    client.post(
        "/tests",
        data={
            "test_id": "never.run.probe",
            "category": "reliability",
            "risk": "low",
            "input": "hi",
            "assertion_name": "response_nonempty",
            "assertion_args": "",
        },
    )
    body = client.get("/tests").text
    assert "never.run.probe" in body
    assert "never run" in body


def test_authored_duplicate_ids_from_different_packs_remain_distinct(tmp_path, monkeypatch):
    # Isolate the merge logic from the shipped packs the library also lists.
    empty_packs = tmp_path / "packs"
    empty_packs.mkdir()
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(empty_packs))
    from agentaudit.web.app import _test_rows

    class FakeStore:
        def list_authored_tests(self, _org_id):
            return [
                {"pack_id": "one", "test_id": "shared.id", "category": "reliability",
                 "risk": "low", "created_by": None, "created_by_email": None},
                {"pack_id": "two", "test_id": "shared.id", "category": "security",
                 "risk": "high", "created_by": None, "created_by_email": None},
            ]

        def list_tests(self, _org_id):
            return []

    rows = _test_rows(FakeStore(), DEFAULT_ORG)
    assert {(row["pack_id"], row["test_id"]) for row in rows} == {
        ("one", "shared.id"),
        ("two", "shared.id"),
    }


# --- T10: one long-lived Store, not one connection per request -------------


def test_store_is_constructed_once_across_many_requests(tmp_path, monkeypatch):
    """The old get_store() built a Store -- and a connection -- per handler call.

    Counting live sqlite3.Connection objects cannot show this: CPython
    refcounting reclaims the orphan as soon as the handler returns. Counting
    constructions is what actually distinguishes the two implementations.
    """
    db = str(tmp_path / "web.db")
    _seed_store(db)
    client = _client(db, monkeypatch)

    import agentaudit.web.app as web_app

    client.get("/runs")  # warm up
    built = 0
    real_init = Store.__init__

    def counting_init(self, *args, **kwargs):
        nonlocal built
        built += 1
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(Store, "__init__", counting_init)
    for _ in range(25):
        assert client.get("/runs").status_code == 200
    assert built == 0, f"{built} Stores built across 25 requests"
    assert web_app._store is not None


def test_store_is_reused_across_requests(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    client = _client(db, monkeypatch)
    from agentaudit.web.app import get_store

    client.get("/runs")
    first = get_store()
    client.get("/runs")
    assert get_store() is first


def test_app_lifespan_can_restart_after_closing_store(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTAUDIT_DB", str(tmp_path / "restart.db"))
    from agentaudit.web.app import app

    with TestClient(app) as first_client:
        assert first_client.get("/runs").status_code == 200
    with TestClient(app) as second_client:
        assert second_client.get("/runs").status_code == 200


def test_store_serves_concurrent_threads(tmp_path):
    """Pool leases connections exclusively and stays within its configured bound."""
    from concurrent.futures import ThreadPoolExecutor

    db = str(tmp_path / "threads.db")
    cfg, _rr, _report = _seed_store(db)
    store = Store(db)

    def read_and_write(n: int) -> int:
        from agentaudit.core.runner import run as run_tests

        rr = run_tests(cfg, [])
        store.save_run(DEFAULT_ORG, cfg, rr, score(rr))
        return len(store.list_runs(DEFAULT_ORG))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(read_and_write, range(8)))
    assert all(r > 0 for r in results)
    assert len(store.list_runs(DEFAULT_ORG)) == 9  # 1 seeded + 8 written
    assert store._pool._created <= 4  # noqa: SLF001 - verify the pool bound


# ---- T13: async submission -----------------------------------------------

_TREASURY = {
    "target": "agentaudit/config/treasury-agent.yaml",
    "packs": "agentaudit/packs/treasury",
}


def test_connect_page_form_posts_to_runs(tmp_path, monkeypatch):
    """The connect page must actually submit a run, not just print a command."""
    client = _client(str(tmp_path / "web.db"), monkeypatch)

    body = client.get("/agents/connect").text

    assert 'action="/runs"' in body
    assert 'method="post"' in body
    assert 'name="target"' in body
    assert 'name="packs"' in body
    # Tooling directories sit beside the packs and are not runnable packs.
    assert ".aislop" not in body
    assert "__pycache__" not in body


def test_tests_page_lists_shipped_tests_that_never_ran(tmp_path, monkeypatch):
    client = _client(str(tmp_path / "web.db"), monkeypatch)

    body = client.get("/tests").text

    assert "email.unauthorized_forward.blocked" in body
    assert "never run" in body


def test_post_runs_rejects_browser_session_without_csrf(tmp_path, monkeypatch):
    """The form carries a csrf_token; a session POST without one must not run."""
    client = _client(str(tmp_path / "web.db"), monkeypatch)

    from agentaudit.web import app as web_app
    from agentaudit.web.auth import Principal

    web_app.app.dependency_overrides[web_app.current_principal] = lambda: Principal(
        DEFAULT_ORG,
        "sub-a",
        "a@test",
        frozenset({"admin"}),
        auth_method="session",
        csrf_token="the-real-token",
    )
    try:
        assert client.post("/runs", data=_TREASURY).status_code == 403
        assert client.post(
            "/runs",
            data={**_TREASURY, "csrf_token": "wrong"},
        ).status_code == 403
        assert client.post(
            "/runs",
            data={**_TREASURY, "csrf_token": "the-real-token"},
            follow_redirects=False,
        ).status_code == 303
    finally:
        web_app.app.dependency_overrides.clear()


def test_post_runs_queues_a_job_without_executing_it(tmp_path, monkeypatch):
    client = _client(str(tmp_path / "web.db"), monkeypatch)

    resp = client.post(
        "/runs",
        data=_TREASURY,
        follow_redirects=False,
    )

    assert resp.status_code == 303
    job_id = resp.headers["location"].rsplit("/", 1)[-1]
    store = Store(str(tmp_path / "web.db"))
    job = store.get_job(DEFAULT_ORG, job_id)
    assert job.state == "queued"
    assert job.run_id is None
    # No run executed inside the handler.
    assert store.list_runs(DEFAULT_ORG) == []
    # The first-party target and pack were imported as rows for the worker.
    assert store.get_target(DEFAULT_ORG, job.target_id)["id"] == "treasury-demo"
    assert len(store.get_pack_tests(DEFAULT_ORG, job.pack_id)) == 6


def test_job_status_reports_queued_running_and_done(tmp_path, monkeypatch):
    client = _client(str(tmp_path / "web.db"), monkeypatch)
    resp = client.post(
        "/runs",
        data=_TREASURY,
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[-1]
    store = Store(str(tmp_path / "web.db"))

    body = client.get(f"/jobs/{job_id}/status").json()
    assert (body["state"], body["running"], body["run_id"]) == ("queued", True, "")
    legacy_body = client.get(
        f"/runs/{job_id}/status", headers={"Accept": "application/json"}
    ).json()
    assert (legacy_body["state"], legacy_body["running"]) == ("queued", True)

    store.claim_job("w1", lease_seconds=-1)
    assert client.get(f"/jobs/{job_id}/status").json()["state"] == "running"

    from agentaudit.worker import work_once

    # w1 "died"; its lease has already expired, so the job comes back.
    assert store.reclaim_jobs(max_attempts=99) == 1
    work_once(store, "w2")
    body = client.get(f"/jobs/{job_id}/status").json()
    assert body["state"] == "done"
    assert body["running"] is False
    assert body["run_id"]
    assert client.get(f"/runs/{body['run_id']}").status_code == 200


def test_job_of_another_org_is_404(tmp_path, monkeypatch):
    client = _client(str(tmp_path / "web.db"), monkeypatch)
    resp = client.post(
        "/runs",
        data=_TREASURY,
        follow_redirects=False,
    )
    job_id = resp.headers["location"].rsplit("/", 1)[-1]

    from agentaudit.web import app as web_app
    from agentaudit.web.auth import Principal

    web_app.app.dependency_overrides[web_app.current_principal] = (
        lambda: Principal("other-org", "sub-b", "b@other.test", frozenset({"admin"}))
    )
    try:
        assert client.get(f"/jobs/{job_id}").status_code == 404
        assert client.get(f"/jobs/{job_id}/status").status_code == 404
    finally:
        web_app.app.dependency_overrides.clear()


def test_run_status_is_always_terminal(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _cfg, rr, _report = _seed_store(db)
    monkeypatch.setenv("AGENTAUDIT_DB", db)
    from agentaudit.web import app as web_app

    body = TestClient(web_app.app).get(
        f"/runs/{rr.run_id}/status", headers={"Accept": "application/json"}
    ).json()

    assert body["running"] is False
    assert body["run_id"] == rr.run_id


# ---- T14: artifact serving ------------------------------------------------


def _seed_artifact(tmp_path, monkeypatch, org: str = DEFAULT_ORG, body: bytes = b'{"trace": 1}'):
    """A run, an artifact row, and the blob on disk under its canonical key."""
    db = str(tmp_path / "web.db")
    _cfg, rr, _report = _seed_store(db)
    store = Store(db)
    path = store.save_artifact(org, rr.run_id, "trace.json", "application/json", len(body))

    root = tmp_path / "artifacts"
    blob = root / path
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(body)
    monkeypatch.setenv("AGENTAUDIT_ARTIFACTS_DIR", str(root))
    return db, rr.run_id, body


def test_artifact_is_served_to_its_own_org(tmp_path, monkeypatch):
    db, _run_id, body = _seed_artifact(tmp_path, monkeypatch)
    client = _client(db, monkeypatch)

    resp = client.get("/artifacts/trace.json")

    assert resp.status_code == 200
    assert resp.content == body


def test_artifact_of_another_org_is_404(tmp_path, monkeypatch):
    db, _run_id, _body = _seed_artifact(tmp_path, monkeypatch)
    client = _client(db, monkeypatch)
    from agentaudit.web import app as web_app
    from agentaudit.web.auth import Principal

    web_app.app.dependency_overrides[web_app.current_principal] = (
        lambda: Principal("other-org", "sub-b", "b@other.test", frozenset({"admin"}))
    )
    try:
        resp = client.get("/artifacts/trace.json")
    finally:
        web_app.app.dependency_overrides.clear()

    assert resp.status_code == 404
    assert "trace" not in resp.text.lower() or "not found" in resp.text.lower()


def test_missing_blob_is_404_not_a_server_error(tmp_path, monkeypatch):
    db, _run_id, _body = _seed_artifact(tmp_path, monkeypatch)
    (tmp_path / "artifacts" / DEFAULT_ORG / _run_id / "trace.json").unlink()
    client = _client(db, monkeypatch)

    assert client.get("/artifacts/trace.json").status_code == 404


def test_artifacts_are_not_exposed_by_a_static_mount(tmp_path, monkeypatch):
    _seed_artifact(tmp_path, monkeypatch)
    from agentaudit.web.app import app as web_app

    mounts = [r for r in web_app.routes if isinstance(getattr(r, "app", None), StaticFiles)]

    assert [m.path for m in mounts] == ["/static"]
    served = {Path(m.app.directory).resolve() for m in mounts}
    assert (tmp_path / "artifacts").resolve() not in served


def test_settings_page_shows_redaction_egress_and_access(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    monkeypatch.delenv("AGENTAUDIT_EGRESS_ALLOW_LOCAL", raising=False)
    client = _client(db, monkeypatch)

    body = client.get("/settings").text

    # built-in masks are compliance evidence: list them, name the mask format
    assert "api_key" in body
    assert "redacted:name" in body
    assert "Allow Local Endpoints" in body
    assert "Disabled" in body
    # the acting principal (dev principal outside OIDC)
    assert "dev@localhost" in body
    assert "admin, viewer" in body


def test_connect_form_preselects_last_used_target_and_pack(tmp_path, monkeypatch):
    client = _client(str(tmp_path / "web.db"), monkeypatch)
    resp = client.post("/runs", data=_TREASURY, follow_redirects=False)
    assert resp.status_code == 303

    body = client.get("/agents/connect").text

    assert f'value="{_TREASURY["target"]}" selected' in body
    assert f'value="{_TREASURY["packs"]}" selected' in body


def test_connect_form_option_values_are_accepted_by_the_run_route(tmp_path, monkeypatch):
    """The dropdown values must round-trip: whatever the form offers, POST /runs
    must accept. Paths relative to the package dir (config/x.yaml) resolve
    against CWD and 400."""
    client = _client(str(tmp_path / "web.db"), monkeypatch)

    body = client.get("/agents/connect").text
    assert f'value="{_TREASURY["target"]}"' in body
    assert f'value="{_TREASURY["packs"]}"' in body


def _seed_planned_store(db_path: str, external: bool = False):
    cfg = TargetConfig(
        id="planned-target",
        agent=CallableSpec(type="callable", callable=f"{MODULE}:create_agent_with_secret"),
        evidence=EvidencePolicy(),
    )
    tests = [
        SchemaTestCase(
            id="a.pass.case",
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        )
    ]
    rr = run(cfg, tests)
    harness = HarnessPlan(
        profile=AgentProfile(id=cfg.id, domain="treasury", sandbox="treasury", tool_use=True),
        selected=[
            SelectedTest(
                test_id="a.pass.case",
                source="local",
                score=2.5,
                reasons=["written for the treasury domain", "risk medium"],
            )
        ],
        excluded=[
            ExcludedTest(
                test_id="garak.dan",
                source="garak",
                reason="garak is not installed on this runner",
            )
        ],
        sandbox="treasury",
    )
    if external:
        harness.selected.append(
            SelectedTest(
                test_id="promptfoo.pii", source="promptfoo", score=2.0, reasons=["risk high"]
            )
        )
    Store(db_path).save_run(DEFAULT_ORG, cfg, rr, score(rr), plan=harness)
    return rr


def test_run_detail_explains_the_selection_when_a_plan_exists(tmp_path, monkeypatch):
    db = str(tmp_path / "planned.db")
    rr = _seed_planned_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}")
    assert resp.status_code == 200
    assert "Why these tests" in resp.text
    assert "written for the treasury domain" in resp.text
    assert "garak is not installed on this runner" in resp.text


def test_run_detail_omits_the_panel_without_a_plan(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _cfg, rr, _report = _seed_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}")
    assert resp.status_code == 200
    assert "Why these tests" not in resp.text


def test_test_detail_shows_why_the_test_was_selected(tmp_path, monkeypatch):
    db = str(tmp_path / "planned.db")
    rr = _seed_planned_store(db)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}/tests/a.pass.case")
    assert resp.status_code == 200
    assert "Why this test ran" in resp.text
    assert "risk medium" in resp.text


def test_run_detail_flags_external_selections_as_unevidenced(tmp_path, monkeypatch):
    db = str(tmp_path / "planned.db")
    rr = _seed_planned_store(db, external=True)
    client = _client(db, monkeypatch)

    resp = client.get(f"/runs/{rr.run_id}")
    assert resp.status_code == 200
    assert "no evidence for them" in resp.text
    assert "promptfoo.pii" in resp.text
