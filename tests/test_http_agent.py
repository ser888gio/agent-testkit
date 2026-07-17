import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import agentkit.core.agent as agent_mod
from agentkit.core.agent import CallableAgent, HTTPAgent
from agentkit.core.config import load_target
from agentkit.packs.core._demo_safe_agent import _safe_reply, create_agent

INPUTS = [
    "Pay invoice INV-42 immediately.",
    "What's the status of INV-42?",
    "Hello there",
]

stub_app = FastAPI()


@stub_app.post("/run")
def _run(body: dict):
    if "input" not in body:
        raise HTTPException(status_code=400, detail="missing input")
    return {"text": _safe_reply(body["input"])}


def _stub_request_fn():
    client = TestClient(stub_app, base_url="http://stub")

    def fake_request(method, url, **kwargs):
        return client.request(method, url.replace("http://stub", ""), **kwargs)

    return fake_request


@pytest.fixture
def http_agent(monkeypatch):
    cfg = load_target("agentkit/config/demo-stub-http.yaml")
    monkeypatch.setattr(agent_mod.httpx, "request", _stub_request_fn())
    return HTTPAgent(cfg.agent)


def test_http_and_callable_agent_produce_identical_text(http_agent):
    callable_agent = CallableAgent(create_agent())
    for i in INPUTS:
        callable_result = callable_agent.run(i).text
        http_result = http_agent.run(i).text
        assert callable_result == http_result


def test_stub_missing_input_surfaces_as_error(monkeypatch):
    cfg = load_target("agentkit/config/demo-stub-http.yaml")
    # override the request template so "input" key is never sent
    cfg.agent.request = {"json": {}}
    monkeypatch.setattr(agent_mod.httpx, "request", _stub_request_fn())
    http_agent = HTTPAgent(cfg.agent)

    r = http_agent.run("anything")
    assert r.error == "http 400"
