from agentkit.cli import app
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
    result = runner.invoke(
        app, ["run", TREASURY_PACK, "--target", TREASURY_TARGET, "--db", db]
    )
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

    report_result = runner.invoke(
        app, ["report", "--run", run_id, "--format", "junit", "--db", db]
    )
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
