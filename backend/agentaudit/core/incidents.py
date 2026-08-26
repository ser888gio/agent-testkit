"""Incident transcript ingestion: paste text in, get structured turns out.

PRD-003 turns production failures into regression candidates. The entry point
to that loop is a human pasting a transcript, so this module defines the
ingest boundary: `parse_transcript` converts plain-text turns into a
`ParsedIncident`, and `redact_incident` applies a `Redactor` over every turn.

Parsing is pure -- text in, model out, no I/O and nothing to configure -- so
the CLI, the dashboard, and tests can call it without a store, an agent, or a
network. It never persists anything and holds no redactor itself.

Redaction is deliberately a separate explicit step, not something parsing does
in passing. The PRD's non-goals forbid storing raw customer data, which makes
redaction a property the caller must be able to prove happened before a value
moves toward persistence -- the same dual-pass discipline the runner uses
(`runner.py` redacts, then `store.py:save_run` re-applies). A parse that
redacted silently would make "was it applied?" unanswerable at the call site;
a named step makes the ordering auditable. Callers must redact before anything
downstream (draft case, archive, store row) ever sees a transcript.

Control-plane side: operates only on already-captured text, never calls an
agent, and imports nothing that reaches the network.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from agentaudit.core.redaction import Redactor

Role = Literal["user", "agent", "tool"]

# A turn marker opens a line ("User:", "Agent:", "Tool search:"), matching
# case-insensitively so pasted transcripts from any source parse the same.
# Anything before the first marker is preamble and is dropped, not guessed at.
_TURN_RE = re.compile(r"^\s*(?:(user|agent)\s*:|tool\s+([^\s:]+)\s*:)\s*(.*)$", re.IGNORECASE)


class IncidentTurn(BaseModel):
    """One speaker turn in a pasted incident transcript."""

    role: Role
    content: str
    tool_name: str | None = None


class ParsedIncident(BaseModel):
    """A parsed transcript: ordered turns plus the final user input."""

    turns: list[IncidentTurn] = Field(default_factory=list)
    final_user_input: str = ""


def parse_transcript(text: str) -> ParsedIncident:
    """Parse a plain-text transcript into ordered turns.

    Grammar: consecutive blocks, each starting with a role marker line --
    ``User:``, ``Agent:`` or ``Tool <name>:`` (case-insensitive). All following
    lines up to the next marker belong to that turn's content. Text before the
    first marker is ignored. The last user turn becomes `final_user_input`.

    Raises:
        ValueError: if the input contains no turns, or no user turn to take
            the final input from.
    """
    turns: list[IncidentTurn] = []
    current_role: Role | None = None
    current_tool: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if current_role is None:
            return
        content = "\n".join(current_lines).strip()
        turns.append(IncidentTurn(role=current_role, content=content, tool_name=current_tool))

    for line in text.splitlines():
        match = _TURN_RE.match(line)
        if match is None:
            # Continuation of the open turn, or preamble before any marker.
            if current_role is not None:
                current_lines.append(line)
            continue
        _flush()
        role_name, tool_name, rest = match.groups()
        if tool_name is not None:
            current_role = "tool"
            current_tool = tool_name
        else:
            current_role = str(role_name).lower()  # type: ignore[assignment]
            current_tool = None
        current_lines = [rest] if rest.strip() else []

    _flush()

    if not turns:
        raise ValueError(
            "transcript contains no turns (expected 'User:'/'Agent:'/Tool <name>: markers)"
        )
    user_turns = [t for t in turns if t.role == "user"]
    if not user_turns:
        raise ValueError("transcript contains no user turn to use as the final input")
    return ParsedIncident(turns=turns, final_user_input=user_turns[-1].content)


def redact_incident(incident: ParsedIncident, redactor: Redactor) -> ParsedIncident:
    """Return a copy of `incident` with every turn's content redacted.

    Explicit second half of the ingest boundary: nothing downstream may see a
    transcript that has not been through this (see module docstring).
    """
    turns = [
        turn.model_copy(update={"content": redactor.redact_text(turn.content)})
        for turn in incident.turns
    ]
    final_user_input = next(t.content for t in reversed(turns) if t.role == "user")
    return incident.model_copy(update={"turns": turns, "final_user_input": final_user_input})
