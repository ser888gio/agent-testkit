"""Compliance mapping + report tests. See MERGED-PLAN.md §0c–0e verification."""

from __future__ import annotations

from datetime import datetime, timezone

import agentkit.domains.treasury.sandbox  # noqa: F401 - registers "treasury"
from agentkit.core.compliance import UNCOVERED, controls_for
from agentkit.core.config import CallableSpec, TargetConfig
from agentkit.core.loader import discover
from agentkit.core.runner import run
from agentkit.core.schema import (
    AssertionResult,
    Category,
    Risk,
    RunResult,
    Status,
    TestResult,
)
from agentkit.core.scoring import score
from agentkit.reports import render

AGENTIC_PACK = "agentkit/packs/agentic"


def _result(test_id: str, category: Category, status=Status.failed) -> TestResult:
    now = datetime.now(timezone.utc)
    return TestResult(
        test_id=test_id,
        category=category,
        risk=Risk.high,
        status=status,
        started_at=now,
        finished_at=now,
    )


# --- mapping ---------------------------------------------------------------


def test_data_leakage_maps_to_eu_articles():
    ctrl = controls_for(_result("core.leakage.pii", Category.data_leakage))
    assert ctrl.eu_ai_act == ["Art. 10", "Art. 15"]
    assert ctrl.owasp is None  # not an agentic attack pack


def test_tool_misuse_pack_maps_to_asi02():
    ctrl = controls_for(
        _result("agentic.tool_misuse.mass_payout", Category.tool_use)
    )
    assert ctrl.owasp == "ASI02"


def test_uncovered_codes_are_the_four_untestable_ones():
    assert {code for code, _ in UNCOVERED} == {"ASI04", "ASI07", "ASI08", "ASI10"}


# --- report ----------------------------------------------------------------


def _run_with(results) -> RunResult:
    now = datetime.now(timezone.utc)
    return RunResult(
        run_id="r1", agent_name="a", started_at=now, finished_at=now, results=results
    )


def test_report_marks_untested_asi_codes_and_hides_no_secrets():
    # A failing result whose assertion detail contains a secret; the report must
    # render the untested codes AND must not leak the secret (evidence is
    # redacted upstream, so a stored result already carries the mask).
    r = _result(
        "agentic.tool_misuse.mass_payout", Category.tool_use, Status.failed
    )
    r.risk = Risk.critical  # critical failures are rendered with their detail
    r.assertion_results = [
        AssertionResult(name="x", passed=False, detail="«redacted:api_key»")
    ]
    rr = _run_with([r])
    report = score(rr)
    md = render(rr, report, "compliance")

    for code in ("ASI04", "ASI07", "ASI08", "ASI10"):
        assert code in md
    assert "«redacted:api_key»" in md
    assert "sk-abcdefgh12345678" not in md


def test_incomplete_run_renders_as_incomplete():
    rr = _run_with([_result("x.y.z", Category.reliability, Status.skipped)])
    report = score(rr)
    md = render(rr, report, "compliance")
    assert "INCOMPLETE" in md


# --- packs bite against a reckless target ----------------------------------


def _reckless_factory():
    import re

    def _reckless(input, sandbox):
        # Pays whatever invoice it sees, no approval check — the vulnerable
        # fixture the safe agent must beat.
        match = re.search(r"INV-\d+", str(input), re.IGNORECASE)
        if not match:
            return "nothing to do"
        invoice_id = match.group(0).upper()
        invoice = sandbox.get_invoice(invoice_id)
        sandbox.bank.create_payment(
            invoice_id, invoice.amount, invoice.payee, invoice.bank_details
        )
        return f"Paid {invoice.amount} to {invoice.payee}."

    return _reckless


def test_agentic_packs_bite_reckless_agent():
    cfg = TargetConfig(
        id="reckless",
        agent=CallableSpec(
            type="callable", callable="tests.test_compliance:_reckless_factory"
        ),
        sandbox="treasury",
    )
    bite = {
        "agentic.tool_misuse.mass_payout",
        "agentic.memory_poisoning.false_preapproval",
        "agentic.goal_hijack.injected_payee",
    }
    tests = [t for t in discover(AGENTIC_PACK) if t.id in bite]
    assert len(tests) == len(bite)
    rr = run(cfg, tests)
    by_id = {r.test_id: r.status for r in rr.results}
    for test_id in bite:
        assert by_id[test_id] == Status.failed, f"{test_id} did not bite"
