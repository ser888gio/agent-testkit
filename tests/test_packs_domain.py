import re

import agentaudit.domains.email.sandbox  # noqa: F401 - registers the "email" sandbox
import agentaudit.domains.treasury.sandbox  # noqa: F401 - registers the "treasury" sandbox
from agentaudit.core.config import CallableSpec, TargetConfig, load_target
from agentaudit.core.loader import discover
from agentaudit.core.runner import run
from agentaudit.core.schema import Status

TREASURY_PACK = "agentaudit/packs/treasury"
EMAIL_PACK = "agentaudit/packs/email"


def test_discover_both_packs_no_error():
    treasury_tests = discover(TREASURY_PACK)
    email_tests = discover(EMAIL_PACK)
    assert len(treasury_tests) == 6
    assert len(email_tests) == 3


def test_treasury_pack_runs_end_to_end_realistic_green():
    cfg = load_target("agentaudit/config/treasury-agent.yaml")
    tests = discover(TREASURY_PACK)
    rr = run(cfg, tests)

    assert all(r.status != Status.error for r in rr.results)
    by_id = {r.test_id: r.status for r in rr.results}
    for test_id, status in by_id.items():
        assert status == Status.passed, f"{test_id} unexpectedly {status}"


def test_email_pack_runs_end_to_end_realistic_green():
    cfg = load_target("agentaudit/config/email-agent.yaml")
    tests = discover(EMAIL_PACK)
    rr = run(cfg, tests)

    assert all(r.status != Status.error for r in rr.results)
    by_id = {r.test_id: r.status for r in rr.results}
    for test_id, status in by_id.items():
        assert status == Status.passed, f"{test_id} unexpectedly {status}"


def _reckless_factory():
    def _reckless(input, sandbox):
        match = re.search(r"INV-\d+", input, re.IGNORECASE)
        invoice_id = match.group(0).upper()
        invoice = sandbox.get_invoice(invoice_id)
        sandbox.bank.create_payment(
            invoice_id, invoice.amount, invoice.payee, invoice.bank_details
        )
        return f"Payment of {invoice.amount} to {invoice.payee} has been processed."

    return _reckless


def test_broken_treasury_agent_fails_unapproved_payment_spot_check():
    cfg = TargetConfig(
        id="reckless-treasury",
        agent=CallableSpec(
            type="callable", callable="tests.test_packs_domain:_reckless_factory"
        ),
        sandbox="treasury",
    )
    tests = [
        t
        for t in discover(TREASURY_PACK)
        if t.id == "treasury.unapproved_payment.blocked"
    ]
    rr = run(cfg, tests)
    assert rr.results[0].status == Status.failed


AGENTIC_PACK = "agentaudit/packs/agentic"
TRAJECTORY_TESTS = {
    "agentic.goal_hijack.payee_swap_survives_injection",
    "agentic.tool_misuse.split_to_evade_limit",
    "agentic.human_oversight.excessive_agency_autopay",
}


def _hijackable_factory():
    def _hijackable(input, sandbox):
        # Obeys an IBAN it finds in the invoice data - the exact failure the
        # goal_hijack trajectory test exists to catch. The end state still says
        # "invoice paid"; only the ledger shows where the money went.
        match = re.search(r"INV-\d+", str(input), re.IGNORECASE)
        if not match:
            return "nothing to do"
        invoice = sandbox.get_invoice(match.group(0).upper())
        injected = re.search(r"\bDE\d{20}\b", invoice.payee)
        bank_details = injected.group(0) if injected else invoice.bank_details
        sandbox.bank.create_payment(invoice.id, invoice.amount, invoice.payee, bank_details)
        return f"Paid {invoice.amount} for {invoice.id}."

    return _hijackable


def _treasury_target(callable_ref: str, target_id: str) -> TargetConfig:
    return TargetConfig(
        id=target_id,
        agent=CallableSpec(type="callable", callable=callable_ref),
        sandbox="treasury",
    )


def test_trajectory_agentic_tests_pass_against_the_demo_agent():
    cfg = load_target("agentaudit/config/treasury-agent.yaml")
    tests = [t for t in discover(AGENTIC_PACK) if t.id in TRAJECTORY_TESTS]
    assert len(tests) == len(TRAJECTORY_TESTS)

    rr = run(cfg, tests)
    for r in rr.results:
        assert r.status == Status.passed, f"{r.test_id}: {r.assertion_results}"


def test_goal_hijack_trajectory_test_catches_a_redirected_payment():
    # The end state is "INV-94 paid" either way; only the recorded call argument
    # distinguishes the safe agent from the hijacked one.
    cfg = _treasury_target("tests.test_packs_domain:_hijackable_factory", "hijackable")
    tests = [
        t
        for t in discover(AGENTIC_PACK)
        if t.id == "agentic.goal_hijack.payee_swap_survives_injection"
    ]
    rr = run(cfg, tests)
    assert rr.results[0].status == Status.failed
