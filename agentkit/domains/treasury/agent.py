"""Deterministic demo treasury agent: approval-aware payment processing."""

from __future__ import annotations

import re
from typing import Callable

from agentkit.domains.treasury.sandbox import TreasurySandbox

_INVOICE_RE = re.compile(r"INV-\d+", re.IGNORECASE)
_PAYEE_RE = re.compile(
    r"\bto\s+([A-Za-z0-9 &.,'-]+?)(?=\s+(?:using|via|account)\b|$)", re.IGNORECASE
)
_BANK_RE = re.compile(r"\baccount\s+([A-Za-z0-9]+)", re.IGNORECASE)


def _reply(input: str, sandbox: TreasurySandbox) -> str:
    match = _INVOICE_RE.search(input)
    if not match:
        return "Please specify which invoice id (e.g. INV-42) you want paid."

    invoice_id = match.group(0).upper()
    invoice = sandbox.get_invoice(invoice_id)
    if invoice is None:
        return f"Cannot process payment: invoice {invoice_id} not found."

    if invoice.paid:
        return (
            f"Cannot process payment: invoice {invoice_id} has already been paid. "
            "This looks like a duplicate request and is not authorized without approval."
        )

    if not invoice.approved:
        return (
            f"Cannot process payment: invoice {invoice_id} requires approval before "
            "it can be paid. Not authorized to proceed without approval."
        )

    if invoice.amount > sandbox.payment_limit:
        return (
            f"Cannot process payment: amount for invoice {invoice_id} exceeds the "
            "payment limit and requires additional approval. Not authorized."
        )

    payee_match = _PAYEE_RE.search(input)
    bank_match = _BANK_RE.search(input)
    requested_payee = payee_match.group(1).strip() if payee_match else invoice.payee
    requested_bank = bank_match.group(1).strip() if bank_match else invoice.bank_details

    if (
        requested_payee.lower() != invoice.payee.lower()
        or requested_bank.upper() != invoice.bank_details.upper()
    ):
        return (
            f"Cannot process payment: requested payee/bank details for invoice "
            f"{invoice_id} do not match records. Not authorized without approval."
        )

    sandbox.bank.create_payment(
        invoice_id, invoice.amount, invoice.payee, invoice.bank_details
    )
    invoice.paid = True
    return (
        f"Payment of {invoice.amount} to {invoice.payee} for invoice "
        f"{invoice_id} has been processed."
    )


def create_agent() -> Callable[[str, TreasurySandbox], str]:
    return _reply
