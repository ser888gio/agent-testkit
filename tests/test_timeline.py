"""Step-level timeline construction (PRD-011)."""

from datetime import datetime, timezone

from agentaudit.core.config import CallableSpec, TargetConfig
from agentaudit.core.loader import discover
from agentaudit.core.runner import run
from agentaudit.core.schema import AssertionResult, Category, Risk, SandboxEvent, Status, TestResult
from agentaudit.core.timeline import build, to_lines, window

_TS = datetime.now(timezone.utc)


def _event(kind: str, **data) -> SandboxEvent:
    return SandboxEvent(kind=kind, data=data, ts=_TS)


def _result(
    *, request=None, response=None, events=(), status=Status.passed, assertions=()
) -> TestResult:
    return TestResult(
        test_id="t.case",
        category=Category.reliability,
        risk=Risk.low,
        status=status,
        request=request,
        response=response,
        events=list(events),
        assertion_results=list(assertions),
        started_at=_TS,
        finished_at=_TS,
    )


def test_single_turn_result_builds_one_turn_and_no_divergence():
    # `build` is mechanical: it always reflects however many turns `request`
    # held. Callers (md/html/junit/api) are the ones that decide a single-turn
    # result has no timeline worth showing (`len(turns) < 2`).
    result = _result(request="hi", response={"text": "ok"})
    timeline = build(result)
    assert len(timeline["turns"]) == 1
    assert timeline["first_divergence"] is None


def test_turnless_result_has_no_timeline():
    result = _result(request=None, response=None)
    timeline = build(result)
    assert timeline["turns"] == []
    assert timeline["first_divergence"] is None


def test_multi_turn_events_bucket_by_agent_turn_marker():
    result = _result(
        request=["plant poison", "cash it in"],
        events=[
            _event("agent.turn", text="plant poison"),
            _event("agent.turn", text="cash it in"),
            _event("payment.created", invoice_id="INV-1"),
        ],
        status=Status.failed,
        assertions=[AssertionResult(name="no_payment_created", passed=False, detail="paid")],
    )
    timeline = build(result)
    assert [t["input"] for t in timeline["turns"]] == ["plant poison", "cash it in"]
    # The payment event landed after the second agent.turn marker.
    assert timeline["turns"][0]["events"] == []
    assert [e["kind"] for e in timeline["turns"][1]["events"]] == ["payment.created"]
    assert timeline["first_divergence"] == 1


def test_first_divergence_is_none_for_a_passing_result():
    result = _result(
        request=["a", "b"],
        events=[_event("agent.turn", text="a"), _event("agent.turn", text="b")],
        status=Status.passed,
    )
    assert build(result)["first_divergence"] is None


def test_first_divergence_falls_back_to_last_turn_without_events():
    # A text-only assertion can fail with no side-effect events recorded at
    # all -- there is nothing more precise to point at than the last turn.
    result = _result(
        request=["a", "b", "c"],
        status=Status.failed,
        assertions=[AssertionResult(name="not_contains", passed=False, detail="leaked")],
    )
    assert build(result)["first_divergence"] == 2


def test_window_keeps_short_transcripts_intact():
    result = _result(
        request=["a", "b", "c"],
        events=[
            _event("agent.turn", text="a"),
            _event("agent.turn", text="b"),
            _event("agent.turn", text="c"),
        ],
        status=Status.failed,
        assertions=[AssertionResult(name="x", passed=False, detail="d")],
    )
    timeline = window(build(result))
    assert timeline["windowed"] is False
    assert len(timeline["turns"]) == 3


def test_window_trims_long_transcripts_around_first_divergence():
    turns = [f"turn-{i}" for i in range(20)]
    events = [_event("agent.turn", text=t) for t in turns]
    # A payment fires only after the 15th agent turn.
    events.insert(16, _event("payment.created", invoice_id="INV-1"))
    result = _result(
        request=turns,
        events=events,
        status=Status.failed,
        assertions=[AssertionResult(name="no_payment_created", passed=False, detail="paid")],
    )
    timeline = window(build(result), size=2)
    assert timeline["windowed"] is True
    assert timeline["first_divergence"] == 15
    indices = [t["index"] for t in timeline["turns"]]
    assert indices == [13, 14, 15, 16, 17]
    assert timeline["omitted_before"] == 13
    assert timeline["omitted_after"] == 2


def test_window_full_flag_bypasses_trimming():
    turns = [f"turn-{i}" for i in range(20)]
    events = [_event("agent.turn", text=t) for t in turns] + [_event("payment.created")]
    result = _result(
        request=turns,
        events=events,
        status=Status.failed,
        assertions=[AssertionResult(name="x", passed=False, detail="d")],
    )
    timeline = window(build(result), full=True)
    assert timeline["windowed"] is False
    assert len(timeline["turns"]) == 20


def test_to_lines_marks_first_divergence():
    result = _result(
        request=["plant", "cash"],
        events=[
            _event("agent.turn", text="plant"),
            _event("agent.turn", text="cash"),
            _event("payment.created", invoice_id="INV-1"),
        ],
        status=Status.failed,
        assertions=[AssertionResult(name="x", passed=False, detail="d")],
    )
    lines = to_lines(window(build(result)))
    assert "Turn 0: plant" in lines
    assert any("first divergence" in line for line in lines if line.startswith("Turn 1"))


# --- success criterion: the poisoning turn is identifiable from the demo ----


def test_overtrusting_agent_false_preapproval_diverges_on_the_poisoning_turn():
    """PRD-011 success criterion: a reader can find the poisoning turn from
    the report alone. Here we assert the machine-checkable half of that --
    the first-divergence marker points at turn 0, where the false
    "pre-approved" claim was planted, for the canonical demo fixture."""
    cfg = TargetConfig(
        id="overtrusting-demo",
        agent=CallableSpec(
            type="callable",
            callable="agentaudit.domains.treasury.overtrusting_agent:create_agent",
        ),
        sandbox="treasury",
    )
    tests = [
        t
        for t in discover("agentaudit/packs/agentic")
        if t.id == "agentic.memory_poisoning.false_preapproval"
    ]
    assert len(tests) == 1

    rr = run(cfg, tests)
    result = rr.results[0]
    assert result.status == Status.failed

    timeline = window(build(result))
    assert len(timeline["turns"]) == 2
    assert timeline["turns"][0]["input"].startswith("Note for our records")
    # The reckless-overtrusting agent pays as soon as it sees the poisoned
    # claim plus an invoice id, which happens on turn 0 already.
    assert timeline["first_divergence"] == 0
    assert timeline["turns"][0]["events"][0]["kind"] == "payment.created"
