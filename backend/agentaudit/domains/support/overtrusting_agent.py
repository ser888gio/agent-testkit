"""Deliberately over-trusting support agent: believes what the prompt claims.

Foil to the hardened :mod:`agentaudit.domains.support.agent`, mirroring
:mod:`agentaudit.domains.treasury.overtrusting_agent`. It trusts a claimed
approval anywhere in the conversation, invents an unknown ticket rather than
refusing it, and never raises -- a pack that should fail comes back
``failed``, not ``error``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from agentaudit.domains.declarative.sandbox import DeclarativeSandbox

_TICKET_RE = re.compile(r"TCK-\d+", re.IGNORECASE)
_APPROVAL_CLAIMS = (
    "pre-approved",
    "already approved",
    "approved",
    "granting myself",
    "no approval needed",
    "cleared by support lead",
    "completed the approval",
)
_UNKNOWN_CUSTOMER = "unknown@external.example"
_ASSUMED_AMOUNT = 100_000


def _reply(text: str, transcript: str, sandbox: DeclarativeSandbox) -> str:
    match = _TICKET_RE.search(text)
    if not match:
        return "Understood, noted for this session."

    ticket_id = match.group(0).upper()
    tickets = sandbox.ledger("tickets")
    ticket = tickets.get(ticket_id)
    known = ticket is not None

    amount = ticket.get("refund_amount", _ASSUMED_AMOUNT) if known else _ASSUMED_AMOUNT
    customer = ticket.get("customer", _UNKNOWN_CUSTOMER) if known else _UNKNOWN_CUSTOMER

    lowered = transcript.lower()
    claimed_approval = any(claim in lowered for claim in _APPROVAL_CLAIMS)
    if known and not ticket.get("approved") and not claimed_approval:
        return (
            f"Cannot process refund: ticket {ticket_id} requires approval. "
            "Not authorized to proceed."
        )

    tickets.update(ticket_id, refunded=True)
    sandbox.mailbox("notifications").send(
        to=customer,
        subject=f"Refund processed for {ticket_id}",
        body=f"Your refund of {amount} for ticket {ticket_id} has been processed.",
    )
    return f"Refund of {amount} for ticket {ticket_id} has been processed."


def create_agent() -> Callable[[str, DeclarativeSandbox], str]:
    # One worker serves every test in a run under isolation, so the
    # transcript lives on the sandbox's event log (cleared per-test reset)
    # rather than a closure -- same reasoning as treasury's foil.
    def _turn(input: str, sandbox: DeclarativeSandbox) -> str:
        text = str(input)
        sandbox.record_event("agent.turn", {"text": text})
        history = [e.data["text"] for e in sandbox.events if e.kind == "agent.turn"]
        return _reply(text, "\n".join(history), sandbox)

    return _turn
