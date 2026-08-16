"""A deliberately boring, safe demo agent for exercising the domain-neutral core pack.

Never echoes its input verbatim and never reveals secrets — used to prove the core
pack can run against *any* target without domain assumptions, and that a properly
hardened agent passes every injection/leakage probe.
"""

from __future__ import annotations

from collections.abc import Callable


def _safe_reply(input: str) -> str:
    if not isinstance(input, str) or not input.strip():
        return "I need more information to help with that."
    return (
        "Thanks for your message. I've noted your request and will proceed "
        "safely within policy."
    )


def create_agent() -> Callable[[str], str]:
    return _safe_reply
