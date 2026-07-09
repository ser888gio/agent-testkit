import re

import agentkit.domains.email.sandbox  # noqa: F401 - registers the "email" sandbox
import agentkit.domains.treasury.sandbox  # noqa: F401 - registers the "treasury" sandbox
from agentkit.core.config import CallableSpec, TargetConfig, load_target
from agentkit.core.loader import discover
from agentkit.core.runner import run
from agentkit.core.schema import Status

TREASURY_PACK = "agentkit/packs/treasury"
EMAIL_PACK = "agentkit/packs/email"


def test_discover_both_packs_no_error():
    treasury_tests = discover(TREASURY_PACK)
    email_tests = discover(EMAIL_PACK)
    assert len(treasury_tests) == 6
    assert len(email_tests) == 3


def test_treasury_pack_runs_end_to_end_realistic_green():
    cfg = load_target("agentkit/config/treasury-agent.yaml")
    tests = discover(TREASURY_PACK)
    rr = run(cfg, tests)

    assert all(r.status != Status.error for r in rr.results)
    by_id = {r.test_id: r.status for r in rr.results}
    for test_id, status in by_id.items():
        assert status == Status.passed, f"{test_id} unexpectedly {status}"


def test_email_pack_runs_end_to_end_realistic_green():
    cfg = load_target("agentkit/config/email-agent.yaml")
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
