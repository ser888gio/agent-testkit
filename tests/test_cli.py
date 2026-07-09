from typer.testing import CliRunner

from agentkit.cli import app

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
