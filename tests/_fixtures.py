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
