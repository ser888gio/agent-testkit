"""Deterministic demo support agent: refund requests against the `support` toolkit.

The `support` sandbox itself is code-free (`agentaudit/toolkits/support.yaml`,
interpreted by `agentaudit.domains.declarative.sandbox`); only the agents
under test here are Python, exactly like `treasury.agent`/`treasury.
overtrusting_agent` are Python against `TreasurySandbox`. Mirrors that
module's structure: a hardened agent and, in `overtrusting_agent.py`, a
deliberately unsafe foil.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from agentaudit.domains.declarative.sandbox import DeclarativeSandbox

_TICKET_RE = re.compile(r"TCK-\d+", re.IGNORECASE)
REFUND_LIMIT = 50_000  # cents ($500), same shape as treasury's payment_limit


def _reply(input: str, sandbox: DeclarativeSandbox) -> str:
    match = _TICKET_RE.search(input)
    if not match:
        return "Please specify which ticket id (e.g. TCK-1) you want refunded."

    ticket_id = match.group(0).upper()
    tickets = sandbox.ledger("tickets")
    ticket = tickets.get(ticket_id)
    if ticket is None:
        return f"Cannot process refund: ticket {ticket_id} not found."

    if ticket.get("refunded"):
        return (
            f"Cannot process refund: ticket {ticket_id} has already been refunded. "
            "This looks like a duplicate request and is not authorized without approval."
        )

    if not ticket.get("approved"):
        return (
            f"Cannot process refund: ticket {ticket_id} requires approval before "
            "it can be refunded. Not authorized to proceed without approval."
        )

    amount = ticket.get("refund_amount", 0)
    if amount > REFUND_LIMIT:
        return (
            f"Cannot process refund: amount for ticket {ticket_id} exceeds the "
            "refund limit and requires additional approval. Not authorized."
        )

    tickets.update(ticket_id, refunded=True)
    customer = ticket.get("customer", "")
    if customer:
        sandbox.mailbox("notifications").send(
            to=customer,
            subject=f"Refund processed for {ticket_id}",
            body=f"Your refund of {amount} for ticket {ticket_id} has been processed.",
        )
    return f"Refund of {amount} for ticket {ticket_id} has been processed."


def create_agent() -> Callable[[str, DeclarativeSandbox], str]:
    return _reply
