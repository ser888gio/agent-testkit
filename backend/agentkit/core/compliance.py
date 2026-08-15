"""Map test results to regulatory controls (EU AI Act / ISO 42001 / NIST / OWASP).

Pure data + lookup — no rules engine, no LLM, no eval. EU/ISO/NIST controls are
inherited by every test through its Category (zero per-test annotation); the OWASP
ASI code is refined from the test-id pack namespace because one Category
(tool_use) spans several ASI codes. See docs/archive/plans/MERGED-PLAN.md §0d.
"""

from __future__ import annotations

from pydantic import BaseModel

from agentkit.core.schema import Category, TestResult

_ART_10 = "Art. 10"
_ART_15 = "Art. 15"


class Control(BaseModel):
    owasp: str | None = None
    eu_ai_act: list[str]
    iso_42001: str
    nist_ai_rmf: str
    severity: str
    description: str


# EU/ISO/NIST controls a test inherits from its Category alone.
CONTROLS_BY_CATEGORY: dict[Category, Control] = {
    Category.endpoint_contract: Control(
        eu_ai_act=["Art. 13"],
        iso_42001="A.6",
        nist_ai_rmf="MEASURE",
        severity="low",
        description="Transparency: agent exposes a well-formed, documented contract.",
    ),
    Category.prompt_injection: Control(
        eu_ai_act=[_ART_15],
        iso_42001="A.8",
        nist_ai_rmf="MEASURE",
        severity="high",
        description="Robustness against adversarial/injection inputs.",
    ),
    Category.data_leakage: Control(
        eu_ai_act=[_ART_10, _ART_15],
        iso_42001="A.7",
        nist_ai_rmf="MAP/MEASURE",
        severity="critical",
        description="Data governance and confidentiality of protected data.",
    ),
    Category.instruction_following: Control(
        eu_ai_act=["Art. 13"],
        iso_42001="A.6",
        nist_ai_rmf="MEASURE",
        severity="medium",
        description="Agent follows its operating instructions predictably.",
    ),
    Category.action_safety: Control(
        eu_ai_act=["Art. 14", "Art. 15"],
        iso_42001="A.9",
        nist_ai_rmf="MANAGE",
        severity="critical",
        description="Human oversight and safe bounds on high-stakes actions.",
    ),
    Category.tool_use: Control(
        eu_ai_act=[_ART_15],
        iso_42001="A.8",
        nist_ai_rmf="MEASURE",
        severity="high",
        description="Tools are invoked within authorized scope and limits.",
    ),
    Category.memory_context: Control(
        eu_ai_act=[_ART_10, _ART_15],
        iso_42001="A.7",
        nist_ai_rmf="MAP/MEASURE",
        severity="high",
        description="Resistance to memory/context poisoning across turns.",
    ),
    Category.reliability: Control(
        eu_ai_act=[_ART_15],
        iso_42001="A.6",
        nist_ai_rmf="MEASURE",
        severity="medium",
        description="Accuracy and consistency of agent behaviour.",
    ),
    Category.performance: Control(
        eu_ai_act=[_ART_15],
        iso_42001="A.6",
        nist_ai_rmf="MEASURE",
        severity="low",
        description="Latency/throughput within operational bounds.",
    ),
}

# OWASP Agentic Top 10 code, keyed on the 2nd test-id segment (the pack name).
OWASP_BY_PACK: dict[str, str] = {
    "goal_hijack": "ASI01",
    "tool_misuse": "ASI02",
    "privilege_abuse": "ASI03",
    "code_execution": "ASI05",
    "memory_poisoning": "ASI06",
    "human_oversight": "ASI09",
}

# ASI codes not black-box testable through a single endpoint. Surfaced as
# explicit gaps by the report, never rendered as passing.
UNCOVERED: list[tuple[str, str]] = [
    ("ASI04", "Resource/economic abuse - needs billing/rate telemetry, not one endpoint."),
    ("ASI07", "Insecure agent supply chain - needs build/artifact provenance."),
    ("ASI08", "Cascading multi-agent failures - needs a multi-agent harness."),
    ("ASI10", "Rogue/insider agents - needs lifecycle and infra access."),
]


def _pack_of(test_id: str) -> str | None:
    parts = test_id.split(".")
    return parts[1] if len(parts) >= 2 else None


def controls_for(result: TestResult) -> Control:
    """EU/ISO/NIST from the category; OWASP refined from the test-id pack namespace."""
    base = CONTROLS_BY_CATEGORY[result.category]
    pack = _pack_of(result.test_id)
    owasp = OWASP_BY_PACK.get(pack) if pack else None
    if owasp is None:
        return base
    return base.model_copy(update={"owasp": owasp})


def _demo() -> None:
    from agentkit.core.schema import Risk, Status

    def _res(test_id: str, cat: Category) -> TestResult:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return TestResult(
            test_id=test_id,
            category=cat,
            risk=Risk.high,
            status=Status.failed,
            started_at=now,
            finished_at=now,
        )

    leak = controls_for(_res("core.leakage.pii", Category.data_leakage))
    assert leak.eu_ai_act == [_ART_10, _ART_15]
    assert leak.owasp is None  # 'leakage' is not an agentic attack pack

    misuse = controls_for(_res("agentic.tool_misuse.mass_payout", Category.tool_use))
    assert misuse.owasp == "ASI02"

    assert {code for code, _ in UNCOVERED} == {"ASI04", "ASI07", "ASI08", "ASI10"}
    print("compliance mapping self-check OK")


if __name__ == "__main__":
    _demo()
