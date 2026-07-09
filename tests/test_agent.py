import httpx
import pytest

from agentkit.core.agent import AgentResponse, CallableAgent, HTTPAgent
from agentkit.core.config import HTTPSpec, ResponseSpec


def test_callable_agent_normalizes_str():
    a = CallableAgent(lambda s: f"echo: {s}")
    r = a.run("hi")
    assert r.text == "echo: hi"
    assert r.latency_ms is not None


def test_callable_agent_normalizes_dict():
    a = CallableAgent(lambda s: {"text": "ok", "extra": 1})
    r = a.run("hi")
    assert r.text == "ok"
    assert r.raw == {"text": "ok", "extra": 1}


def test_callable_agent_passthrough_agentresponse():
    a = CallableAgent(lambda s: AgentResponse(text="already"))
    r = a.run("hi")
    assert r.text == "already"
    assert r.latency_ms is not None


def test_callable_agent_passes_sandbox_when_accepted():
    captured = {}

    def fn(input, sandbox=None):
        captured["sandbox"] = sandbox
        return "ok"

    sentinel = object()
    a = CallableAgent(fn, sandbox=sentinel)
    a.run("hi")
    assert captured["sandbox"] is sentinel


def test_callable_agent_error_never_raises():
    def fn(input):
        raise RuntimeError("boom")

    a = CallableAgent(fn)
    r = a.run("hi")
    assert r.error == "boom"


def test_contains_any_all_case_insensitive():
    r = AgentResponse(text="Payment Blocked")
    assert r.contains_any(["blocked"])
    assert r.contains_all(["payment", "BLOCKED"])
    assert not r.contains_any(["approved"])


def _http_agent(monkeypatch, handler) -> HTTPAgent:
    import agentkit.core.agent as agent_mod

    spec = HTTPSpec(
        type="http",
        endpoint="http://test/run",
        request={"json": {"input": "{{ input }}"}},
        response=ResponseSpec(text_path="$.text"),
    )

    def fake_request(method, url, **kwargs):
        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            return client.request(method, url, **kwargs)

    monkeypatch.setattr(agent_mod.httpx, "request", fake_request)
    return HTTPAgent(spec)


@pytest.fixture
def http_ok(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "ok"})

    return _http_agent(monkeypatch, handler)


def test_http_agent_happy_path(http_ok):
    r = http_ok.run("hi")
    assert r.text == "ok"
    assert r.status_code == 200
    assert r.error is None


@pytest.fixture
def http_500(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    return _http_agent(monkeypatch, handler)


def test_http_agent_500_sets_error(http_500):
    r = http_500.run("hi")
    assert r.error == "http 500"
    assert r.status_code == 500


@pytest.fixture
def http_timeout(monkeypatch):
    def handler(request: httpx.Request):
        raise httpx.TimeoutException("timed out", request=request)

    return _http_agent(monkeypatch, handler)


def test_http_agent_timeout(http_timeout):
    r = http_timeout.run("hi")
    assert r.error == "timeout"


@pytest.fixture
def http_missing_path(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"other": "value"})

    return _http_agent(monkeypatch, handler)


def test_http_agent_missing_text_path(http_missing_path):
    r = http_missing_path.run("hi")
    assert r.error == "response_path_not_found"
    assert r.raw == {"other": "value"}
