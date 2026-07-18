from pathlib import Path

from fastapi.testclient import TestClient

from agentkit.core.config import CallableSpec, TargetConfig
from agentkit.core.redaction import EvidencePolicy
from agentkit.core.runner import run
from agentkit.core.schema import Assertion, Category, TestCase
from agentkit.core.scoring import score
from agentkit.core.store import DEFAULT_ORG, Store

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
        TestCase(
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
    assert "Apply Filters" not in resp.text


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
    assert 'href="/harness" class="active" aria-current="page"' in resp.text


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
    assert 'href="/harness" class="active" aria-current="page"' in resp.text


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
    assert 'href="/" class="active" aria-current="page"' in resp.text


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
    assert "AGENTKIT_OIDC" not in resp.text
    assert 'href="/settings" class="active" aria-current="page"' in resp.text


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


def test_create_test_stores_db_row(tmp_path, monkeypatch):
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

    # Stored as an org-scoped DB row, and nothing was written to the packs dir.
    assert not packs.exists()
    rows = Store(db).get_pack_tests(DEFAULT_ORG, "user")
    assert len(rows) == 1
    # round-trips through the real loader
    from agentkit.core.loader import load_tests_from_rows

    cases = load_tests_from_rows(rows)
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
    assert "duplicate test id" in second.text


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
    from agentkit.core.store import Store as _Store

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
    import agentkit.web as web_pkg

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
    monkeypatch.setenv("AGENTKIT_OIDC_JWKS_URL", "https://kc.test/certs")
    monkeypatch.setenv("AGENTKIT_OIDC_ISSUER", "https://kc.test/realms/agentkit")
    monkeypatch.setenv("AGENTKIT_OIDC_AUDIENCE", "agentkit-web")


def _concrete_paths() -> list[tuple[str, str]]:
    """Every app route, with path params filled in. Static mount excluded."""
    from agentkit.web.app import app

    out = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if not path.startswith("/") or path.startswith("/static"):
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
    monkeypatch.setenv("AGENTKIT_DB", str(tmp_path / "web.db"))
    _oidc_env(monkeypatch)
    from agentkit.web.app import app

    client = TestClient(app)
    paths = _concrete_paths()
    assert paths, "route table came back empty; the introspection is wrong"

    unprotected = []
    for method, path in paths:
        resp = client.request(method, path, params={"a": "x", "b": "y",
                                                    "target": "t", "packs": "p"})
        if resp.status_code != 401:
            unprotected.append((method, path, resp.status_code))
    assert not unprotected


def test_run_of_another_org_is_404_not_403(tmp_path, monkeypatch):
    """Org B must not learn that org A's run id exists."""
    db = str(tmp_path / "web.db")
    _cfg, rr, _report = _seed_store(db)
    monkeypatch.setenv("AGENTKIT_DB", db)

    from agentkit.web import app as web_app
    from agentkit.web.auth import Principal

    client = TestClient(web_app.app)
    # The run was seeded under DEFAULT_ORG; the dev principal is that org.
    assert client.get(f"/runs/{rr.run_id}").status_code == 200

    web_app.app.dependency_overrides[web_app.current_principal] = (
        lambda: Principal("other-org", "sub-b", "b@other.test")
    )
    try:
        resp = client.get(f"/runs/{rr.run_id}")
    finally:
        web_app.app.dependency_overrides.clear()
    assert resp.status_code == 404


def test_runs_of_another_org_are_not_listed(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    _seed_store(db)
    monkeypatch.setenv("AGENTKIT_DB", db)

    from agentkit.web import app as web_app
    from agentkit.web.auth import Principal

    client = TestClient(web_app.app)
    assert "web-target" in client.get("/runs").text

    web_app.app.dependency_overrides[web_app.current_principal] = (
        lambda: Principal("other-org", "sub-b", "b@other.test")
    )
    try:
        for path in ("/runs", "/agents", "/tests"):
            assert "web-target" not in client.get(path).text, path
    finally:
        web_app.app.dependency_overrides.clear()


def _seed_attributed_store(db: str) -> str:
    """One CLI-launched run (no principal) plus one launched by a human."""
    cfg, _rr, _report = _seed_store(db)
    from agentkit.core.runner import run as run_tests

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
    monkeypatch.setenv("AGENTKIT_DB", db)
    from agentkit.web.app import app

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
    monkeypatch.setenv("AGENTKIT_PACKS", str(packs))
    monkeypatch.setenv("AGENTKIT_DB", db)

    from agentkit.web import app as web_app
    from agentkit.web.auth import Principal

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
        lambda: Principal("org-b", "sub-b", "b@other.test")
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
    source = Path("frontend/agentkit/web/app.py").read_text(encoding="utf-8")
    assert "write_text" not in source
    assert "mkdir" not in source


def test_authored_test_shows_before_it_has_ever_run(tmp_path, monkeypatch):
    db = str(tmp_path / "web.db")
    Store(db)
    monkeypatch.setenv("AGENTKIT_DB", db)
    from agentkit.web.app import app

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
