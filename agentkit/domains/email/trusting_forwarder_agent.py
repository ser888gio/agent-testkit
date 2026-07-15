"""Deliberately trusting email agent: flags phishing but forwards anywhere.

Foil to the hardened :mod:`agentkit.domains.email.agent`, and a different
failure profile from :mod:`agentkit.domains.email.naive_agent` (which fails
everything). This one *does* detect and flag phishing, but it has no
external-recipient guard, so it forwards to any address on request — failing
``unauthorized_forward`` while passing ``phishing``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from agentkit.domains.email.sandbox import EmailSandbox, Message

_MESSAGE_ID_RE = re.compile(r"\bmessage\s+([A-Za-z0-9_-]+)", re.IGNORECASE)
_FORWARD_RE = re.compile(
    r"\b(?:forward|send)\b.*?\bto\s+([\w.+-]+@[\w-]+\.[\w.-]+)", re.IGNORECASE
)
_PHISHING_KEYWORDS = ("verify", "suspend", "click", "urgent", "password", "login")


def _find_message(input: str, sandbox: EmailSandbox) -> Message | None:
    explicit = _MESSAGE_ID_RE.search(input)
    if explicit:
        return sandbox.get_message(explicit.group(1))
    for msg in sandbox.inbox.messages:
        if re.search(rf"\b{re.escape(msg.id)}\b", input, re.IGNORECASE):
            return msg
    return None


def _is_phishing(msg: Message, sandbox: EmailSandbox) -> bool:
    if not sandbox.inbox.is_external(msg.sender):
        return False
    body = msg.body.lower()
    return any(kw in body for kw in _PHISHING_KEYWORDS)


def _reply(input: str, sandbox: EmailSandbox) -> str:
    msg = _find_message(input, sandbox)
    if msg is None:
        return "Please specify which message you want handled."

    # Phishing detection is intact...
    if _is_phishing(msg, sandbox):
        if "phishing" not in msg.labels:
            msg.labels.append("phishing")
        return (
            f"Message {msg.id} looks like a phishing attempt. Flagged and not "
            "acted on."
        )

    # ...but forwarding has no external-recipient guard.
    forward_match = _FORWARD_RE.search(input)
    if forward_match:
        target = forward_match.group(1).rstrip(".")
        sandbox.inbox.send(
            to=target, subject=msg.subject, body=msg.body, forwarded_from=msg.sender
        )
        return f"Forwarded message {msg.id} to {target}."

    return f"Summary of {msg.id}: {msg.subject} — {msg.body[:80]}"


def create_agent() -> Callable[[str, EmailSandbox], str]:
    return _reply
