"""The one assembled audit run both entry points go through."""

from datetime import datetime, timezone

import agentaudit.core.audit as audit
from agentaudit.core.audit import execute
from agentaudit.core.config import CallableSpec, TargetConfig
from agentaudit.core.egress import ValidatedEndpoint
from agentaudit.core.redaction import EvidencePolicy, Redactor
from agentaudit.core.schema import Assertion, Category, RunResult, TestCase

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
