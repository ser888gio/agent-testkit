"""Normalized agent adapter: the interface the runner + assertions code against."""

from __future__ import annotations

import importlib
import inspect
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import httpx

from agentkit.core.config import CallableSpec, HTTPSpec, TargetConfig

_HTTPX_REQUEST_KWARGS = {"json", "params", "data", "content"}


@dataclass
class AgentResponse:
    text: str = ""
    raw: Any = None
    latency_ms: float | None = None
    status_code: int | None = None
    error: str | None = None

    def contains_any(self, needles: list[str]) -> bool:
        lowered = self.text.lower()
        return any(n.lower() in lowered for n in needles)

    def contains_all(self, needles: list[str]) -> bool:
        lowered = self.text.lower()
        return all(n.lower() in lowered for n in needles)


class Agent(Protocol):
    def run(self, input: str | dict) -> AgentResponse: ...


class CallableAgent:
    def __init__(self, fn: Callable[..., Any], sandbox: Any = None):
        self.fn = fn
        self.sandbox = sandbox
        try:
            self._accepts_sandbox = "sandbox" in inspect.signature(fn).parameters
        except (TypeError, ValueError):
            self._accepts_sandbox = False

    def run(self, input: str | dict) -> AgentResponse:
        start = time.perf_counter()
        try:
            if self._accepts_sandbox:
                result = self.fn(input, sandbox=self.sandbox)
            else:
                result = self.fn(input)
        except Exception as exc:  # noqa: BLE001 - adapter must never raise
            latency_ms = (time.perf_counter() - start) * 1000
            return AgentResponse(latency_ms=latency_ms, error=str(exc))

        latency_ms = (time.perf_counter() - start) * 1000

        if isinstance(result, AgentResponse):
            result.latency_ms = latency_ms
            return result
        if isinstance(result, str):
            return AgentResponse(text=result, raw=result, latency_ms=latency_ms)
        if isinstance(result, dict):
            return AgentResponse(
                text=str(result.get("text", "")), raw=result, latency_ms=latency_ms
            )
        return AgentResponse(text=str(result), raw=result, latency_ms=latency_ms)


def _render_template(template: Any, input: str | dict) -> Any:
    if isinstance(template, str):
        if template == "{{ input }}":
            return input
        if "{{ input }}" in template:
            return template.replace("{{ input }}", str(input))
        return template
    if isinstance(template, dict):
        return {k: _render_template(v, input) for k, v in template.items()}
    if isinstance(template, list):
        return [_render_template(v, input) for v in template]
    return template


def _extract_path(body: Any, path: str) -> tuple[bool, Any]:
    parts = path.lstrip("$").lstrip(".").split(".") if path.strip("$") else []
    current = body
    for part in parts:
        if not part:
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


class HTTPAgent:
    def __init__(self, spec: HTTPSpec):
        self.spec = spec

    def run(self, input: str | dict) -> AgentResponse:
        spec = self.spec
        rendered = _render_template(spec.request, input)
        kwargs = {k: v for k, v in rendered.items() if k in _HTTPX_REQUEST_KWARGS}

        start = time.perf_counter()
        try:
            response = httpx.request(
                spec.method,
                spec.endpoint,
                headers=spec.headers,
                timeout=spec.timeout_s,
                **kwargs,
            )
        except httpx.TimeoutException:
            latency_ms = (time.perf_counter() - start) * 1000
            return AgentResponse(latency_ms=latency_ms, error="timeout")
        except httpx.HTTPError as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            return AgentResponse(latency_ms=latency_ms, error=str(exc))

        latency_ms = (time.perf_counter() - start) * 1000

        try:
            body = response.json()
        except ValueError:
            body = response.text

        if response.is_error:
            return AgentResponse(
                text="",
                raw=body,
                latency_ms=latency_ms,
                status_code=response.status_code,
                error=f"http {response.status_code}",
            )

        found, value = _extract_path(body, spec.response.text_path)
        if not found:
            return AgentResponse(
                text="",
                raw=body,
                latency_ms=latency_ms,
                status_code=response.status_code,
                error="response_path_not_found",
            )

        return AgentResponse(
            text=str(value),
            raw=body,
            latency_ms=latency_ms,
            status_code=response.status_code,
        )


def build_agent(config: TargetConfig, sandbox: Any = None) -> Agent:
    agent_spec = config.agent
    if isinstance(agent_spec, CallableSpec):
        module_path, _, attr = agent_spec.callable.partition(":")
        module = importlib.import_module(module_path)
        factory = getattr(module, attr)
        fn = factory()
        return CallableAgent(fn, sandbox=sandbox)
    if isinstance(agent_spec, HTTPSpec):
        return HTTPAgent(agent_spec)
    raise ValueError(f"unknown agent spec type: {type(agent_spec)!r}")
