"""Shared non-test-collected fixtures for tests/test_cli.py."""

from __future__ import annotations

import re


def create_reckless_agent():
    def _reckless(input, sandbox):
        match = re.search(r"INV-\d+", input, re.IGNORECASE)
        invoice_id = match.group(0).upper()
        invoice = sandbox.get_invoice(invoice_id)
        sandbox.bank.create_payment(
            invoice_id, invoice.amount, invoice.payee, invoice.bank_details
        )
        return f"Payment of {invoice.amount} to {invoice.payee} has been processed."

    return _reckless


def create_retry_loop_agent():
    """Retries a hardcoded payment 3x on every call, no lookup needed.

    Used to prove an incident-derived candidate (which carries no `setup:`,
    unlike a hand-authored pack test) can still reproduce a real failure: this
    agent needs no seeded invoice, so a `no_repeated_tool`/`tool_not_called`
    candidate built straight from a transcript reproduces the same
    infinite-retry failure the transcript describes.
    """

    def _retry(input, sandbox):
        for _ in range(3):
            sandbox.bank.create_payment("INV-99", 100, "Acme Corp", "DE00000000000000000000")
        return "payment retried after a timeout, sent 3 times"

    return _retry
