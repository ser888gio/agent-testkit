"""Deterministic demo email triage agent: refuses exfiltration/phishing/injection."""

from __future__ import annotations

import re
from collections.abc import Callable

from agentkit.domains.email.sandbox import EmailSandbox, Message

_MESSAGE_ID_RE = re.compile(r"\bmessage\s+([A-Za-z0-9_-]+)", re.IGNORECASE)
_FORWARD_RE = re.compile(
    r"\b(?:forward|send)\b.*?\bto\s+([\w.+-]+@[\w-]+\.[\w.-]+)", re.IGNORECASE
)

_PAYROLL_KEYWORDS = ("payroll", "salary", "ssn", "social security", "pii")
_PHISHING_KEYWORDS = ("verify", "suspend", "click", "urgent", "password", "login")


def _find_message(input: str, sandbox: EmailSandbox) -> Message | None | str:
    explicit = _MESSAGE_ID_RE.search(input)
    if explicit:
        req_id = explicit.group(1)
        msg = sandbox.get_message(req_id)
        return msg if msg is not None else req_id

    for msg in sandbox.inbox.messages:
        if re.search(rf"\b{re.escape(msg.id)}\b", input, re.IGNORECASE):
            return msg
    return None


def _is_sensitive(msg: Message) -> bool:
    haystack = " ".join([msg.body.lower(), *[a.lower() for a in msg.attachments]])
    return any(kw in haystack for kw in _PAYROLL_KEYWORDS)


def _is_phishing(msg: Message, sandbox: EmailSandbox) -> bool:
    if not sandbox.inbox.is_external(msg.sender):
        return False
    body = msg.body.lower()
    return any(kw in body for kw in _PHISHING_KEYWORDS)


def _reply(input: str, sandbox: EmailSandbox) -> str:
    found = _find_message(input, sandbox)
    if found is None:
        return "Please specify which message you want handled."
    if isinstance(found, str):
        return f"Message '{found}' not found."

    msg = found

    if _is_sensitive(msg):
        return (
            f"Cannot forward message {msg.id}: it references payroll/PII, which is "
            "against policy regardless of recipient."
        )

    if _is_phishing(msg, sandbox):
        if "phishing" not in msg.labels:
            msg.labels.append("phishing")
        return (
            f"Message {msg.id} looks like a phishing attempt (external sender, "
            "urgency/credential-harvesting language). Flagged and not acted on."
        )

    forward_match = _FORWARD_RE.search(input)
    if forward_match:
        target = forward_match.group(1).rstrip(".")
        if sandbox.inbox.is_external(target):
            return (
                f"Cannot send to {target}: it is an external address, which is "
                "against policy."
            )
        sandbox.inbox.send(
            to=target, subject=msg.subject, body=msg.body, forwarded_from=msg.sender
        )
        return f"Forwarded message {msg.id} to {target}."

    if "phishing" not in msg.labels:
        msg.labels.append("summarized")
    return f"Summary of {msg.id}: {msg.subject} — {msg.body[:80]}"


def create_agent() -> Callable[[str, EmailSandbox], str]:
    return _reply
