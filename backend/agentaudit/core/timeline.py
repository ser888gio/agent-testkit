"""Step-level timelines: turn-by-turn view of a multi-turn `TestResult`.

Purely a rendering derivation over data the runner already persists -- no new
capture path. `TestResult.request` holds every turn sent (the loader's
`turns:` list, or an adaptive strategy's generated turns); `TestResult.events`
holds the redacted sandbox side-effect stream in call order (PRD-011). This
module lines the two up by turn and locates the first-divergence turn: the
turn during which the earliest event relevant to the first failing assertion
fired.

Control-plane only: consumes an already-redacted `TestResult` and never
touches a live agent, mirroring `findings.py` / `runview.py`. `reports/` and
`web/` both call this so there is exactly one construction, not three.
"""

from __future__ import annotations

from typing import Any

from agentaudit.core.findings import failed_assertions
from agentaudit.core.schema import SandboxEvent, TestResult

# Sandbox events that mark a new turn (see `overtrusting_agent.py`). Turn
# boundaries beyond this are inferred from the fixed number of `request`
# entries: even when no agent-side turn event is recorded, the count of turns
# sent is known and events are split evenly across the trailing turn.
TURN_MARKER_EVENT = "agent.turn"

# Long-transcript default: keep this many turns before/after first-divergence.
DEFAULT_WINDOW = 2


def _turn_inputs(result: TestResult) -> list[str]:
    request = result.request
    if isinstance(request, list):
        return [str(t) for t in request]
    if request is None:
        return []
    return [str(request)]


def _bucket_events(events: list[SandboxEvent], turn_count: int) -> list[list[SandboxEvent]]:
    """Assign each event to a turn index, in call order.

    When the agent records a `TURN_MARKER_EVENT` per turn (as the treasury
    demo fixture does), events fall into the bucket of the most recent marker
    seen so far. Without markers, there is no signal to split on, so every
    event lands in the last turn -- that undercounts precision but never
    fabricates a turn boundary the evidence does not support.
    """
    # Markers are excluded from the output buckets: the turn's own text is
    # already shown as that turn's `input`, so re-listing the marker event
    # there would just duplicate it.
    buckets: list[list[SandboxEvent]] = [[] for _ in range(max(turn_count, 1))]
    current = 0
    marker_seen = False
    for event in events:
        if event.kind == TURN_MARKER_EVENT:
            current = min(current + 1, turn_count - 1) if marker_seen else 0
            marker_seen = True
            continue
        buckets[current].append(event)
    return buckets


def _first_divergence(result: TestResult, turn_count: int, buckets: list[list[Any]]) -> int | None:
    """The turn whose bucket contains the earliest event tied to the first
    failing assertion, i.e. the earliest state-changing (non-marker) event
    at or after which the failing precondition existed. Falls back to the
    turn of the first tool-effect event overall, since most safety assertions
    (`no_payment_created`, `no_external_forward`, ...) fail because *some*
    side effect happened, regardless of which assertion names it.
    """
    if not failed_assertions(result):
        return None
    for index, bucket in enumerate(buckets):
        if bucket:
            return index
    # No side-effect events at all (e.g. a text-only assertion failed) --
    # nothing to point at more precisely than the final turn.
    return turn_count - 1 if turn_count else None


def build(result: TestResult) -> dict[str, Any]:
    """One `TestResult` as a turn-by-turn timeline.

    Shape (also the JSON report's optional `timeline` block):
        {
          "turns": [{"index": int, "input": str, "events": [...]}],
          "final_response": Any,
          "first_divergence": int | None,
        }
    Empty `turns` for a single-turn or turn-less result (e.g. an ERROR before
    any request was sent) -- callers should treat that as "no timeline to show".
    """
    inputs = _turn_inputs(result)
    turn_count = len(inputs)
    buckets = _bucket_events(list(result.events), turn_count) if turn_count else []

    turns = [
        {
            "index": i,
            "input": inputs[i],
            "events": [e.model_dump(mode="json") for e in buckets[i]],
        }
        for i in range(turn_count)
    ]

    return {
        "turns": turns,
        "final_response": result.response,
        "first_divergence": _first_divergence(result, turn_count, buckets),
    }


def window(
    timeline: dict[str, Any], *, full: bool = False, size: int = DEFAULT_WINDOW
) -> dict[str, Any]:
    """The timeline as rendered by default: a window around first-divergence
    for long transcripts, unless `full` is requested.

    Short transcripts (<= 2*size + 1 turns) are never truncated -- windowing a
    transcript a reader could scan in one screen just adds a "show more" click
    for no benefit.
    """
    turns = timeline["turns"]
    divergence = timeline["first_divergence"]
    if full or divergence is None or len(turns) <= 2 * size + 1:
        return {**timeline, "windowed": False, "omitted_before": 0, "omitted_after": 0}

    start = max(0, divergence - size)
    end = min(len(turns), divergence + size + 1)
    return {
        **timeline,
        "turns": turns[start:end],
        "windowed": True,
        "omitted_before": start,
        "omitted_after": len(turns) - end,
    }


def to_lines(timeline: dict[str, Any]) -> list[str]:
    """Plain-text rendering shared by the Markdown report and the JUnit
    `<system-out>` attachment, so the two formats never drift apart."""
    lines: list[str] = []
    if timeline["omitted_before"]:
        lines.append(f"  ... {timeline['omitted_before']} earlier turn(s) omitted ...")
    for turn in timeline["turns"]:
        marker = " <-- first divergence" if turn["index"] == timeline["first_divergence"] else ""
        lines.append(f"Turn {turn['index']}: {turn['input']}{marker}")
        for event in turn["events"]:
            lines.append(f"    [{event['kind']}] {event['data']}")
    if timeline["omitted_after"]:
        lines.append(f"  ... {timeline['omitted_after']} later turn(s) omitted ...")
    return lines
