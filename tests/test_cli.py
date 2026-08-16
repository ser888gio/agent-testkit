import json

from agentkit.cli import app
from agentkit.core.store import DEFAULT_ORG, Store
from typer.testing import CliRunner

runner = CliRunner()

TREASURY_TARGET = "agentkit/config/treasury-agent.yaml"
TREASURY_PACK = "agentkit/packs/treasury"

RECKLESS_TARGET_YAML = """
id: reckless-treasury
agent:
  type: callable
  callable: tests._fixtures:create_reckless_agent
sandbox: treasury
"""


def test_run_exits_zero_when_all_pass(tmp_path):
    db = str(tmp_path / "a.db")
    result = runner.invoke(app, ["run", TREASURY_PACK, "--target", TREASURY_TARGET, "--db", db])
    assert result.exit_code == 0, result.output


def test_run_exits_one_on_critical_failure(tmp_path):
    db = str(tmp_path / "a.db")
    reckless_target = tmp_path / "reckless.yaml"
    reckless_target.write_text(RECKLESS_TARGET_YAML, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            TREASURY_PACK,
            "--target",
            str(reckless_target),
            "--db",
            db,
            "--tag",
            "action_safety",
        ],
    )
    assert result.exit_code == 1, result.output


def test_run_exits_two_on_missing_target(tmp_path):
    db = str(tmp_path / "a.db")
    result = runner.invoke(
        app, ["run", TREASURY_PACK, "--target", "does/not/exist.yaml", "--db", db]
    )
    assert result.exit_code == 2, result.output


def test_run_requires_exactly_one_of_target_or_endpoint(tmp_path):
    db = str(tmp_path / "a.db")
    for args in (
        [],  # neither
        ["--endpoint", "https://a.example.com/x", "--target", TREASURY_TARGET],  # both
    ):
        result = runner.invoke(app, ["run", TREASURY_PACK, "--db", db, *args])
        assert result.exit_code == 2, result.output


def test_run_endpoint_builds_a_target_named_after_the_host(tmp_path):
    """--endpoint stands in for a config file: default request/response shape."""
    from agentkit.cli import _load_target_or_exit

    cfg = _load_target_or_exit(None, "https://agent.example.com/chat")
    assert cfg.id == "agent.example.com"
    assert cfg.agent.type == "http"
    assert cfg.agent.endpoint == "https://agent.example.com/chat"
    assert cfg.agent.request == {"json": {"input": "{{ input }}"}}
    assert cfg.agent.response.text_path == "$.text"
    assert cfg.sandbox is None


def test_run_fail_under_boundary_exits_one(tmp_path):
    db = str(tmp_path / "a.db")
    reckless_target = tmp_path / "reckless.yaml"
    reckless_target.write_text(RECKLESS_TARGET_YAML, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            TREASURY_PACK,
            "--target",
            str(reckless_target),
            "--db",
            db,
            "--fail-under",
            "0.99",
            "--no-block-on-critical",
        ],
    )
    assert result.exit_code == 1, result.output


def test_run_format_json_prints_machine_readable_summary(tmp_path):
    db = str(tmp_path / "a.db")
    result = runner.invoke(
        app,
        [
            "run",
            TREASURY_PACK,
            "--target",
            TREASURY_TARGET,
            "--db",
            db,
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    import json

    payload = json.loads(result.output)
    assert "overall_score" in payload
    assert "gate_passed" in payload


ONE_TEST_PACK_YAML = """
id: attack.smoke
category: prompt_injection
input: "say hello"
assertions:
  - name: response_nonempty
"""


def _one_test_pack(tmp_path):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "smoke.yaml").write_text(ONE_TEST_PACK_YAML, encoding="utf-8")
    return str(pack)


def test_run_attack_expands_each_test_into_variants(tmp_path):
    db = str(tmp_path / "a.db")
    args = ["run", _one_test_pack(tmp_path), "--target", TREASURY_TARGET, "--db", db]

    plain = runner.invoke(app, args)
    assert "(1 tests)" in plain.output, plain.output

    expanded = runner.invoke(app, [*args, "--attack", "base64,rot13"])
    assert "(3 tests)" in expanded.output, expanded.output


def test_run_unknown_attack_exits_two(tmp_path):
    db = str(tmp_path / "a.db")
    result = runner.invoke(
        app,
        [
            "run",
            _one_test_pack(tmp_path),
            "--target",
            TREASURY_TARGET,
            "--db",
            db,
            "--attack",
            "nope",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "unknown attack transform" in result.output


def test_compare_exits_one_on_critical_regression(tmp_path):
    import json

    db = str(tmp_path / "a.db")

    good_run = runner.invoke(
        app,
        [
            "run",
            TREASURY_PACK,
            "--target",
            TREASURY_TARGET,
            "--db",
            db,
            "--format",
            "json",
            "--tag",
            "action_safety",
        ],
    )
    run_a = json.loads(good_run.output)["run_id"]

    reckless_target = tmp_path / "reckless.yaml"
    reckless_target.write_text(RECKLESS_TARGET_YAML, encoding="utf-8")
    bad_run = runner.invoke(
        app,
        [
            "run",
            TREASURY_PACK,
            "--target",
            str(reckless_target),
            "--db",
            db,
            "--format",
            "json",
            "--no-block-on-critical",
        ],
    )
    run_b = json.loads(bad_run.output)["run_id"]

    result = runner.invoke(app, ["compare", run_a, run_b, "--db", db])
    assert result.exit_code == 1, result.output
    assert "CRITICAL REGRESSIONS" in result.output


def test_report_format_junit_emits_xml_to_stdout(tmp_path):
    db = str(tmp_path / "a.db")
    run_result = runner.invoke(
        app,
        [
            "run",
            TREASURY_PACK,
            "--target",
            TREASURY_TARGET,
            "--db",
            db,
            "--format",
            "json",
        ],
    )
    import json

    run_id = json.loads(run_result.output)["run_id"]

    report_result = runner.invoke(app, ["report", "--run", run_id, "--format", "junit", "--db", db])
    assert report_result.exit_code == 0, report_result.output
    assert report_result.output.strip().startswith("<testsuite")


def test_ui_rejects_public_bind_without_oidc(monkeypatch):
    monkeypatch.delenv("AGENTKIT_AUTH_MODE", raising=False)
    result = runner.invoke(app, ["ui", "--host", "0.0.0.0"])
    assert result.exit_code == 1
    assert "requires AGENTKIT_AUTH_MODE=oidc" in result.output


def test_ui_rejects_dev_mode_on_public_bind(monkeypatch):
    monkeypatch.setenv("AGENTKIT_AUTH_MODE", "dev")
    result = runner.invoke(app, ["ui", "--host", "0.0.0.0"])
    assert result.exit_code == 1
    assert "loopback-only" in result.output


def test_ui_rejects_incomplete_oidc_configuration(monkeypatch):
    monkeypatch.setenv("AGENTKIT_AUTH_MODE", "oidc")
    for name in (
        "AGENTKIT_OIDC_JWKS_URL",
        "AGENTKIT_OIDC_ISSUER",
        "AGENTKIT_OIDC_AUDIENCE",
        "AGENTKIT_OIDC_CLIENT_ID",
        "AGENTKIT_OIDC_REDIRECT_URI",
    ):
        monkeypatch.delenv(name, raising=False)
    result = runner.invoke(app, ["ui"])
    assert result.exit_code == 1
    assert "OIDC is incompletely configured" in result.output


def test_purge_requires_a_retention_flag(tmp_path):
    db = str(tmp_path / "cli.db")

    result = runner.invoke(app, ["purge", "--db", db])
    assert result.exit_code == 2

    result = runner.invoke(app, ["purge", "--db", db, "--keep-last", "5"])
    assert result.exit_code == 0
    assert "purged 0 runs" in result.output


def test_plan_explains_what_it_selected_and_what_it_skipped():
    result = runner.invoke(app, ["plan", TREASURY_PACK, "--target", TREASURY_TARGET])

    assert result.exit_code == 0, result.output
    assert "domain=treasury" in result.output
    assert "why:" in result.output
    assert "not tested" in result.output


def test_plan_json_is_a_harness_plan():
    result = runner.invoke(
        app, ["plan", TREASURY_PACK, "--target", TREASURY_TARGET, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["profile"]["domain"] == "treasury"
    assert payload["selected"]
    assert all(entry["reasons"] for entry in payload["selected"])


def test_run_with_plan_persists_the_plan_and_honours_the_budget(tmp_path):
    db = str(tmp_path / "planned.db")

    result = runner.invoke(
        app,
        [
            "run",
            TREASURY_PACK,
            "--target",
            TREASURY_TARGET,
            "--db",
            db,
            "--plan",
            "--max-tests",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    store = Store(db)
    run_id = store.list_runs(DEFAULT_ORG)[0].id
    stored = store.get_run_plan(DEFAULT_ORG, run_id)
    assert stored is not None
    assert len(stored.selected) == 1
    assert stored.stop_conditions.max_tests == 1


def test_max_tests_without_plan_is_rejected(tmp_path):
    db = str(tmp_path / "a.db")
    result = runner.invoke(
        app,
        ["run", TREASURY_PACK, "--target", TREASURY_TARGET, "--db", db, "--max-tests", "2"],
    )
    assert result.exit_code == 2, result.output


def test_report_plan_format_renders_the_stored_rationale(tmp_path):
    db = str(tmp_path / "planned.db")
    assert (
        runner.invoke(
            app, ["run", TREASURY_PACK, "--target", TREASURY_TARGET, "--db", db, "--plan"]
        ).exit_code
        == 0
    )
    run_id = Store(db).list_runs(DEFAULT_ORG)[0].id

    result = runner.invoke(app, ["report", "--run", run_id, "--format", "plan", "--db", db])

    assert result.exit_code == 0, result.output
    assert "## Discovered profile" in result.output
    assert "## Not tested" in result.output


def test_report_plan_format_is_honest_about_an_unplanned_run(tmp_path):
    db = str(tmp_path / "plain.db")
    assert (
        runner.invoke(
            app, ["run", TREASURY_PACK, "--target", TREASURY_TARGET, "--db", db]
        ).exit_code
        == 0
    )
    run_id = Store(db).list_runs(DEFAULT_ORG)[0].id

    result = runner.invoke(app, ["report", "--run", run_id, "--format", "plan", "--db", db])

    assert result.exit_code == 0, result.output
    assert "without a planner" in result.output
