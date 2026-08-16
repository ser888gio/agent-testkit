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


def _http_agent(handler) -> HTTPAgent:
    spec = HTTPSpec(
        type="http",
        endpoint="http://test/run",
        request={"json": {"input": "{{ input }}"}},
        response=ResponseSpec(text_path="$.text"),
    )
    return HTTPAgent(spec, transport=httpx.MockTransport(handler))


@pytest.fixture
def http_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "ok"})

    return _http_agent(handler)


def test_http_agent_happy_path(http_ok):
    r = http_ok.run("hi")
    assert r.text == "ok"
    assert r.status_code == 200
    assert r.error is None


@pytest.fixture
def http_500():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    return _http_agent(handler)


def test_http_agent_500_sets_error(http_500):
    r = http_500.run("hi")
    assert r.error == "http 500"
    assert r.status_code == 500


@pytest.fixture
def http_timeout():
    def handler(request: httpx.Request):
        raise httpx.TimeoutException("timed out", request=request)

    return _http_agent(handler)


def test_http_agent_timeout(http_timeout):
    r = http_timeout.run("hi")
    assert r.error == "timeout"


@pytest.fixture
def http_missing_path():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"other": "value"})

    return _http_agent(handler)


def test_http_agent_missing_text_path(http_missing_path):
    r = http_missing_path.run("hi")
    assert r.error == "response_path_not_found"
    assert r.raw == {"other": "value"}


def test_http_agent_pinned_endpoint_sends_sni_and_host():
    """A ValidatedEndpoint dials the pinned address with SNI + Host overridden.

    Regression: this path passes `extensions=`, which only Client.request
    accepts -- the module-level httpx.request() rejected it, erroring every
    hosted HTTP run.
    """
    from agentkit.core.egress import ValidatedEndpoint

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host"] = request.headers.get("Host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, json={"text": "ok"})

    validated = ValidatedEndpoint(
        url="https://agent.example.com/run",
        host="agent.example.com",
        port=443,
        address="93.184.216.34",
    )
    agent = HTTPAgent(
        HTTPSpec(
            type="http",
            endpoint=validated.url,
            request={"json": {"input": "{{ input }}"}},
            response=ResponseSpec(text_path="$.text"),
        ),
        endpoint=validated,
        transport=httpx.MockTransport(handler),
    )

    r = agent.run("hi")
    assert r.error is None
    assert r.text == "ok"
    assert seen["url"] == "https://93.184.216.34/run"
    assert seen["host"] == "agent.example.com"
    assert seen["sni"] == "agent.example.com"
