"""Tiny deterministic demo agent shared by the in-process and HTTP paths.

Used to prove `HTTPAgent` (black-box) and `CallableAgent` (in-process) are
faithful to each other for identical inputs.
"""

from __future__ import annotations

from typing import Callable


def _reply(input: str) -> str:
    text = input.lower()
    if "pay" in text and "invoice" in text:
        return "Payment requires approval before it can be processed."
    return f"Received: {input}"


def create_agent() -> Callable[[str], str]:
    return _reply
