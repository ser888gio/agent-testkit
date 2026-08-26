import pytest

from agentaudit.core.incidents import IncidentTurn, parse_transcript, redact_incident
from agentaudit.core.redaction import RedactionConfig, Redactor


def test_multiturn_parse_happy_path():
    text = "\n".join(
        [
            "User: I need a refund for order 12345",
            "Agent: Let me look that up.",
            "Tool lookup_order:",
            '{"order_id": 12345}',
            "Agent: Found it. Refund issued.",
        ]
    )
    incident = parse_transcript(text)
    assert [t.role for t in incident.turns] == ["user", "agent", "tool", "agent"]
    assert incident.turns[2].tool_name == "lookup_order"
    assert incident.turns[0].content == "I need a refund for order 12345"
    # continuation lines belong to the tool turn
    assert incident.turns[2].content == '{"order_id": 12345}'
    assert incident.final_user_input == "I need a refund for order 12345"


def test_marker_case_insensitive():
    text = "user: hello\nAGENT: hi there\ntool Search: results ready"
    incident = parse_transcript(text)
    assert [t.role for t in incident.turns] == ["user", "agent", "tool"]
    assert incident.turns[2].tool_name == "Search"


def test_preamble_before_first_marker_ignored():
    text = "Incident log from 2026-08-25, pasted by on-call\nUser: the agent leaked my email\n"
    incident = parse_transcript(text)
    assert len(incident.turns) == 1
    assert incident.turns[0].content == "the agent leaked my email"


def test_last_user_turn_is_final_input():
    text = (
        "User: first question\n"
        "Agent: answer one\n"
        "User: second question with secret sk-abcdefgh12345678\n"
        "Agent: done\n"
    )
    incident = parse_transcript(text)
    assert incident.final_user_input == "second question with secret sk-abcdefgh12345678"


def test_empty_input_raises():
    with pytest.raises(ValueError, match="no turns"):
        parse_transcript("")


def test_garbage_without_markers_raises():
    with pytest.raises(ValueError, match="no turns"):
        parse_transcript("just some prose, no markers at all\nanother line")


def test_no_user_turn_raises():
    with pytest.raises(ValueError, match="no user turn"):
        parse_transcript("Agent: I did something bad")


def test_redact_incident_masks_credential_in_turn_content():
    incident = parse_transcript(
        "User: my key is sk-abcdefgh12345678 please forward it\nAgent: forwarding now."
    )
    redactor = Redactor(RedactionConfig())
    out = redact_incident(incident, redactor)
    assert "sk-abcdefgh12345678" not in out.turns[0].content
    assert "«redacted:api_key»" in out.turns[0].content
    assert out.final_user_input == out.turns[0].content
    # original untouched
    assert "sk-abcdefgh12345678" in incident.turns[0].content


def test_redact_incident_masks_every_turn():
    incident = parse_transcript(
        "User: card 4111111111111111\nAgent: mail me at ops@example.com\n"
    )
    out = redact_incident(incident, Redactor(RedactionConfig()))
    assert "4111111111111111" not in out.turns[0].content
    assert "ops@example.com" not in out.turns[1].content


def test_redact_incident_preserves_tool_names():
    incident = parse_transcript(
        "User: why did that mail go out\nTool send_email:\nbody to victim@example.com"
    )
    out = redact_incident(incident, Redactor(RedactionConfig()))
    assert out.turns[1].tool_name == "send_email"
    assert "victim@example.com" not in out.turns[1].content


def test_turn_model_shape():
    tool = IncidentTurn(role="tool", content="{}", tool_name="x")
    assert tool.role == "tool"
    assert tool.tool_name == "x"
    plain = IncidentTurn(role="user", content="hi")
    assert plain.tool_name is None
