"""A naive, over-compliant demo agent: says yes to whatever it is asked.

Foil to `_demo_safe_agent.py`. It exists so the core jailbreak ladders can be
shown to fail against a plausible bad agent -- a test no agent fails asserts
nothing. Sandbox-free like the rest of `packs/core`: it never touches state,
it just claims compliance in its own words, which is exactly what the
jailbreak tests' `not_contains` assertions watch for.
"""

from __future__ import annotations

from collections.abc import Callable


def _naive_reply(input: str) -> str:
    if not isinstance(input, str) or not input.strip():
        return "Sure, I'll take care of that."
    return "Understood, proceeding right away. The payment has been processed."


def create_agent() -> Callable[[str], str]:
    return _naive_reply
