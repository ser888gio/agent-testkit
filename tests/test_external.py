"""Execution of external eval tools (core/external.py).

Neither promptfoo nor garak is a dependency, so every test here drives a stub
binary: a tiny Python script on PATH that behaves the way the real tool would.
That keeps the process, timeout, and teardown paths honestly exercised without
installing a Node toolchain in CI.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentaudit.core.adapters import ADAPTERS, GarakAdapter, PromptfooAdapter
from agentaudit.core.egress import ValidatedEndpoint
from agentaudit.core.external import (
    ExternalRunError,
    run_external,
)
from agentaudit.core.profile import AgentProfile
from agentaudit.core.redaction import EvidencePolicy
from agentaudit.core.schema import Status, TestResult

ENDPOINT = ValidatedEndpoint(
    url="https://agent.example.test/run",
    host="agent.example.test",
    port=443,
    address="93.184.216.34",
)


def _profile(**kw) -> AgentProfile:
    return AgentProfile(id="p1", domain="treasury", **kw)


def _stub(tmp_path: Path, name: str, body: str) -> Path:
    """Put an executable `name` on PATH that runs `body` as Python."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / f"{name}.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")

    if sys.platform == "win32":
        # A .cmd shim is what `shutil.which` finds on Windows.
        launcher = bindir / f"{name}.cmd"
        launcher.write_text(f'@echo off\n"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = bindir / name
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        launcher.chmod(0o755)
    return bindir


class _FakeAdapter:
    """Minimal adapter: writes a report we control, normalizes it trivially."""

    name = "faketool"

    def __init__(self, report: str = '{"ok": true}', *, argv_extra: list[str] | None = None):
        self.report = report
        self.argv_extra = argv_extra or []
        self.normalized: list[str] = []

    def available(self) -> bool:
        return True

    def catalog(self, profile):
        return []

    def invocation(self, profile, endpoint, workdir):
        report = workdir / "out.json"
        argv = ["faketool", "--endpoint", endpoint, "--out", str(report), *self.argv_extra]
        return argv, report

    def normalize(self, raw, *, evidence=None, started_at=None):
        self.normalized.append(raw)
        return [
            TestResult(
                test_id="faketool.case",
                category="reliability",
                risk="medium",
                status=Status.failed,
                started_at=started_at or datetime.now(timezone.utc),
                finished_at=started_at or datetime.now(timezone.utc),
            )
        ]


WRITES_REPORT = """
    import sys
    out = sys.argv[sys.argv.index("--out") + 1]
    with open(out, "w", encoding="utf-8") as fh:
        fh.write('{"ok": true}')
"""

WRITES_NOTHING = """
    import sys
    print("boom: could not reach the endpoint", file=sys.stderr)
    sys.exit(3)
"""

HANGS = """
    import time
    time.sleep(60)
"""


def _path_with(monkeypatch, bindir: Path) -> None:
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")


def test_a_successful_scan_is_normalized_into_results(tmp_path, monkeypatch):
    _path_with(monkeypatch, _stub(tmp_path, "faketool", WRITES_REPORT))
    adapter = _FakeAdapter()

    run = run_external(adapter, _profile(), ENDPOINT, workdir=tmp_path)

    assert run.tool == "faketool"
    assert [r.test_id for r in run.results] == ["faketool.case"]
    assert run.returncode == 0
    assert run.failed == 1
    # The adapter saw the report the tool actually wrote.
    assert adapter.normalized == ['{"ok": true}']


def test_a_missing_binary_is_a_reason_not_a_crash(tmp_path):
    with pytest.raises(ExternalRunError, match="not installed"):
        run_external(_FakeAdapter(), _profile(), ENDPOINT, workdir=tmp_path)


def test_a_tool_that_writes_no_report_fails_with_its_stderr(tmp_path, monkeypatch):
    _path_with(monkeypatch, _stub(tmp_path, "faketool", WRITES_NOTHING))

    with pytest.raises(ExternalRunError, match="without writing a report") as exc:
        run_external(_FakeAdapter(), _profile(), ENDPOINT, workdir=tmp_path)
    # The reason has to survive: "it failed" is not a finding, "it could not
    # reach the endpoint" is.
    assert "could not reach the endpoint" in str(exc.value)


def test_an_overrunning_scan_is_killed_and_reported(tmp_path, monkeypatch):
    _path_with(monkeypatch, _stub(tmp_path, "faketool", HANGS))

    with pytest.raises(ExternalRunError, match="budget and was killed"):
        run_external(_FakeAdapter(), _profile(), ENDPOINT, workdir=tmp_path, timeout_s=1.0)


def test_an_unreadable_report_is_not_silently_zero_results(tmp_path, monkeypatch):
    """A report we cannot parse must never look like a clean scan."""
    _path_with(monkeypatch, _stub(tmp_path, "faketool", WRITES_REPORT))

    class _Broken(_FakeAdapter):
        def normalize(self, raw, *, evidence=None, started_at=None):
            raise ValueError("no 'results' list")

    with pytest.raises(ExternalRunError, match="unreadable report"):
        run_external(_Broken(), _profile(), ENDPOINT, workdir=tmp_path)


def test_a_broken_mapping_is_not_blamed_on_the_tool(tmp_path, monkeypatch):
    """ValidationError means our adapter is wrong, not that the report was bad.

    ValidationError subclasses ValueError, so it would otherwise be swallowed
    into "wrote an unreadable report" and send the reader to debug promptfoo
    instead of `adapters.py`.
    """
    _path_with(monkeypatch, _stub(tmp_path, "faketool", WRITES_REPORT))

    class _BadMapping(_FakeAdapter):
        def normalize(self, raw, *, evidence=None, started_at=None):
            return [TestResult(test_id="x")]  # missing required fields

    with pytest.raises(ValidationError):
        run_external(_BadMapping(), _profile(), ENDPOINT, workdir=tmp_path)


def test_stderr_in_the_error_is_redacted(tmp_path, monkeypatch):
    """Tool stderr echoes prompts and can carry a credential."""
    leaky = """
        import sys
        print("failed sending sk-abcdefgh12345678 to the agent", file=sys.stderr)
        sys.exit(1)
    """
    _path_with(monkeypatch, _stub(tmp_path, "faketool", leaky))

    with pytest.raises(ExternalRunError) as exc:
        run_external(_FakeAdapter(), _profile(), ENDPOINT, workdir=tmp_path)
    assert "sk-abcdefgh12345678" not in str(exc.value)


def test_the_workdir_is_cleaned_up_even_after_a_failure(tmp_path, monkeypatch):
    _path_with(monkeypatch, _stub(tmp_path, "faketool", WRITES_NOTHING))
    before = set(tmp_path.iterdir())

    with pytest.raises(ExternalRunError):
        run_external(_FakeAdapter(), _profile(), ENDPOINT, workdir=tmp_path)

    # No temporary scan directory survives; a report can hold prompts and
    # responses, so leaving one behind leaks evidence outside the policy.
    assert set(tmp_path.iterdir()) == before


def test_evidence_policy_reaches_the_adapter(tmp_path, monkeypatch):
    _path_with(monkeypatch, _stub(tmp_path, "faketool", WRITES_REPORT))
    seen = {}

    class _Recording(_FakeAdapter):
        def normalize(self, raw, *, evidence=None, started_at=None):
            seen["evidence"] = evidence
            return []

    policy = EvidencePolicy(store_response=False)
    run_external(_Recording(), _profile(), ENDPOINT, workdir=tmp_path, evidence=policy)

    assert seen["evidence"] is policy


# --- the real adapters describe a runnable invocation ----------------------


def test_promptfoo_invocation_writes_a_config_and_names_a_report(tmp_path):
    argv, report = PromptfooAdapter().invocation(_profile(), ENDPOINT.url, tmp_path)

    assert argv[0] == "promptfoo"
    config = json.loads((tmp_path / "promptfooconfig.json").read_text(encoding="utf-8"))
    assert config["targets"][0]["config"]["url"] == ENDPOINT.url
    assert str(report) in argv
    assert report.parent == tmp_path


def test_garak_invocation_matches_its_report_prefix(tmp_path):
    argv, report = GarakAdapter().invocation(_profile(tool_use=True), ENDPOINT.url, tmp_path)

    prefix = argv[argv.index("--report_prefix") + 1]
    # If these drift apart the scan runs and the report is never found.
    assert report.name.startswith(prefix)
    assert report.parent == tmp_path


def test_a_generated_config_carries_no_literal_credential(tmp_path):
    """Headers are rendered as {{env.VAR}}; a real token must never be written."""
    adapter = PromptfooAdapter()
    config = adapter.to_config(_profile(), ENDPOINT.url, header_env={"Authorization": "TOKEN"})

    assert config["targets"][0]["config"]["headers"]["Authorization"] == "{{env.TOKEN}}"


def test_every_registered_adapter_can_describe_an_invocation(tmp_path):
    """A new adapter that ranks tests but cannot be run is a plan that lies."""
    for name, adapter in ADAPTERS.items():
        work = tmp_path / name
        work.mkdir()
        argv, report = adapter.invocation(_profile(tool_use=True), ENDPOINT.url, work)
        assert argv and argv[0] == name
        assert report.parent == work
