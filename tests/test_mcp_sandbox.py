from agentaudit.core.sandbox import build_sandbox
from agentaudit.domains.mcp.sandbox import McpToolboxSandbox


def _sandbox() -> McpToolboxSandbox:
    sb = McpToolboxSandbox()
    sb.reset()
    return sb


def test_recorded_invocation_appears_in_events_and_diff():
    sb = _sandbox()
    sb.apply_setup({"tools": [{"name": "fetch_document"}]})
    before = sb.snapshot()

    sb.invoke("fetch_document", {"id": "q3"})
    after = sb.snapshot()

    assert sb.call_count("fetch_document") == 1
    kinds = [e.kind for e in sb.events]
    assert "fetch_document" in kinds
    event = next(e for e in sb.events if e.kind == "fetch_document")
    assert set(event.data) == {"args_hash", "response_hash", "ok"}
    diff = sb.diff(before, after)
    added_calls = diff["added"].get("calls", []) + diff["changed"].get("calls", {}).get("after", [])
    assert len(added_calls) == 1
    call = added_calls[0]
    assert call["tool"] == "fetch_document"
    assert call["args_hash"] and call["response_hash"]


def test_reset_clears_tools_calls_and_events():
    sb = _sandbox()
    sb.apply_setup({"tools": [{"name": "send_to_endpoint"}]})
    sb.invoke("send_to_endpoint", {"text": "leak"})

    sb.reset()

    assert sb.tools == {}
    assert sb.calls == []
    assert sb.events == []
    assert sb.snapshot() == {"tools": [], "calls": []}


def test_registered_name_resolves_via_build_sandbox():
    sb = build_sandbox("mcp")
    assert isinstance(sb, McpToolboxSandbox)


def test_unknown_setup_key_raises():
    sb = _sandbox()
    try:
        sb.apply_setup({"invoices": []})
    except ValueError as exc:
        assert "cannot apply setup key 'invoices'" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown setup key")
