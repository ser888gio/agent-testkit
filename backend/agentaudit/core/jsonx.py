"""Extract a JSON object from model output that may not be only JSON.

Every model call in this codebase that asks for JSON gets it back wrapped in
something: a ```json fence, a "Sure, here you go:" preamble, or an explanation
appended after the closing brace. `json.loads` fails on all three, and the
failure mode is a silently dropped turn or a lost verdict.

The scanner walks braces while tracking string state, so a `{` inside a string
value does not throw the depth count off.

Ported from garak's `detectors/agent_breaker.AgentBreakerResult._extract_json`
(NVIDIA, Apache-2.0).
"""

from __future__ import annotations

import json
from typing import Any


def _balanced_span(text: str, start: int) -> int:
    """Index just past the `}` closing the object that opens at `start`.

    Tracks string state so a brace inside a string value does not throw the
    depth count off. Returns -1 when the object never closes.
    """
    depth = 0
    in_string = False
    escaped = False
    for i, char in enumerate(text[start:], start=start):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def extract_json(text: str) -> dict[str, Any]:
    """The first complete JSON object in `text`.

    Raises `json.JSONDecodeError` when there is no balanced object to find.
    """
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(parsed, dict):
            return parsed
        raise json.JSONDecodeError("top-level JSON value is not an object", text, 0)

    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("no JSON object found", text, 0)

    end = _balanced_span(text, start)
    if end == -1:
        raise json.JSONDecodeError("unterminated JSON object", text, start)
    return json.loads(text[start:end])
