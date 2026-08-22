"""The one assembled audit run both entry points go through."""

from datetime import datetime, timezone

import agentaudit.core.audit as audit
from agentaudit.core.audit import execute, run_external
from agentaudit.core.config import CallableSpec, HTTPSpec, TargetConfig
from agentaudit.core.egress import ValidatedEndpoint
from agentaudit.core.profile import AgentProfile, HarnessPlan, SelectedTest
from agentaudit.core.redaction import EvidencePolicy, Redactor
from agentaudit.core.schema import (
    Assertion,
    Category,
    Risk,
    RunResult,
    Status,
    TestCase,
    TestResult,
)

MODULE = "tests.test_audit"


def create_agent():
    return lambda input: "ok"


def _target() -> TargetConfig:
    return TargetConfig(
        id="audit-target",
        agent=CallableSpec(type="callable", callable=f"{MODULE}:create_agent"),
        sandbox=None,
        evidence=EvidencePolicy(),
    )


def _case(test_id: str) -> TestCase:
    return TestCase(
        id=test_id,
        category=Category.reliability,
        input="hi",
        assertions=[Assertion(name="response_nonempty")],
    )


def _spy(monkeypatch) -> list[dict]:
    """Replace the runner so the assembly can be observed without spawning one."""
    seen: list[dict] = []

    def fake_run(cfg, cases, *, redactor=None, endpoint=None, on_test=None):
        seen.append({"cases": list(cases), "redactor": redactor, "endpoint": endpoint})
        now = datetime.now(timezone.utc)
        return RunResult(
            run_id="r", agent_name=cfg.id, started_at=now, finished_at=now, results=[]
        )

    monkeypatch.setattr(audit, "run_tests", fake_run)
    return seen


def test_discovery_uses_the_same_bound_path_as_the_graded_run(monkeypatch):
    seen = _spy(monkeypatch)
    redactor = Redactor(EvidencePolicy().redact)
    endpoint = ValidatedEndpoint(
        url="https://agent.partner.test/run",
        host="agent.partner.test",
        port=443,
        address="93.184.216.34",
    )

    execute(_target(), [_case("a.b.one")], redactor=redactor, endpoint=endpoint, plan=True)

    # Probes and the graded run alike. A probe that skipped the caller's egress
    # decision would be a second execution path around it.
    assert len(seen) > 1
    assert all(call["endpoint"] is endpoint and call["redactor"] is redactor for call in seen)


def test_without_a_plan_nothing_probes_the_endpoint(monkeypatch):
    seen = _spy(monkeypatch)

    audit_run = execute(_target(), [_case("a.b.one")], attack_transforms=["base64"])

    assert len(seen) == 1
    assert audit_run.plan is None
    # The original plus one variant per transform.
    assert [c.id for c in seen[0]["cases"]] == ["a.b.one", "a.b.one__base64"]


def _plan_selecting(*sources: str) -> tuple[HarnessPlan, list[SelectedTest]]:
    profile = AgentProfile(id="audit-target", tool_use=True)
    selected = [
        SelectedTest(test_id=f"{source}.thing", source=source, score=1.0)
        for source in sources
    ]
    return HarnessPlan(profile=profile, selected=selected, excluded=[]), selected


def _http_target() -> TargetConfig:
    return TargetConfig(
        id="audit-target",
        agent=HTTPSpec(type="http", endpoint="https://agent.example/chat"),
        sandbox=None,
        evidence=EvidencePolicy(),
    )


def test_a_callable_target_has_no_url_to_hand_a_scanner():
    harness, selected = _plan_selecting("garak")

    results, remaining = run_external(_target(), harness, selected)

    assert results == []
    assert remaining == selected


def test_an_executed_selection_stops_being_unexecuted(monkeypatch):
    harness, selected = _plan_selecting("garak", "some-other-tool")
    now = datetime.now(timezone.utc)
    evidence = TestResult(
        test_id="garak.dan.0",
        category=Category.prompt_injection,
        risk=Risk.high,
        status=Status.failed,
        started_at=now,
        finished_at=now,
    )
    monkeypatch.setattr(
        audit.ADAPTERS["garak"], "execute", lambda *a, **k: [evidence], raising=True
    )

    results, remaining = run_external(_http_target(), harness, selected)

    assert results == [evidence]
    # Nothing here runs "some-other-tool", and a plan that claimed coverage for
    # it anyway would be reporting evidence that does not exist.
    assert [choice.source for choice in remaining] == ["some-other-tool"]
