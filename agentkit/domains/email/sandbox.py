"""Fake inbox + contacts + outbound ledger for the email domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agentkit.core.sandbox import Sandbox, register_sandbox

DEFAULT_INTERNAL_DOMAIN = "acme.example"


@dataclass
class Message:
    id: str
    sender: str
    to: str
    subject: str
    body: str
    attachments: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


@dataclass
class SentMail:
    to: str
    subject: str
    body: str
    forwarded_from: str | None
    ts: datetime


class FakeInbox:
    def __init__(self, sandbox: "EmailSandbox"):
        self.messages: list[Message] = []
        self.contacts: set[str] = set()
        self.sent: list[SentMail] = []
        self._sandbox = sandbox

    def send(
        self, to: str, subject: str, body: str, forwarded_from: str | None = None
    ) -> SentMail:
        sent = SentMail(
            to=to,
            subject=subject,
            body=body,
            forwarded_from=forwarded_from,
            ts=datetime.now(timezone.utc),
        )
        self.sent.append(sent)
        self._sandbox.record_event(
            "mail.sent",
            {"to": to, "subject": subject, "forwarded_from": forwarded_from},
        )
        return sent

    def mail_count(self, to: str | None = None) -> int:
        if to is None:
            return len(self.sent)
        return sum(1 for m in self.sent if m.to.lower() == to.lower())

    def no_mail_sent_to(self, address: str) -> bool:
        return self.mail_count(address) == 0

    def is_external(self, address: str) -> bool:
        domain = address.rsplit("@", 1)[-1].lower()
        known = {c.lower() for c in self.contacts}
        return (
            address.lower() not in known
            and domain != self._sandbox.internal_domain.lower()
        )


@register_sandbox("email")
class EmailSandbox(Sandbox):
    def __init__(self) -> None:
        super().__init__()
        self.internal_domain: str = DEFAULT_INTERNAL_DOMAIN
        self.inbox = FakeInbox(self)

    def reset(self) -> None:
        self.internal_domain = DEFAULT_INTERNAL_DOMAIN
        self.inbox = FakeInbox(self)
        self._clear_events()

    def apply_setup(self, setup: dict[str, Any]) -> None:
        for key, value in setup.items():
            if key == "internal_domain":
                self.internal_domain = value
            elif key == "contacts":
                self.inbox.contacts = set(value)
            elif key == "messages":
                for raw in value:
                    self.inbox.messages.append(Message(**raw))
            else:
                raise self._unknown_setup_key(key)

    def snapshot(self) -> dict[str, Any]:
        return {
            "internal_domain": self.internal_domain,
            "contacts": sorted(self.inbox.contacts),
            "messages": [
                {
                    "id": m.id,
                    "sender": m.sender,
                    "to": m.to,
                    "subject": m.subject,
                    "body": m.body,
                    "attachments": list(m.attachments),
                    "labels": list(m.labels),
                }
                for m in self.inbox.messages
            ],
            "sent": [
                {
                    "to": s.to,
                    "subject": s.subject,
                    "body": s.body,
                    "forwarded_from": s.forwarded_from,
                    "ts": s.ts.isoformat(),
                }
                for s in self.inbox.sent
            ],
        }

    def get_message(self, id: str) -> Message | None:
        return next((m for m in self.inbox.messages if m.id == id), None)
