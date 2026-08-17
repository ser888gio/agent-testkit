"""Normalized agent adapter: the interface the runner + assertions code against."""

from __future__ import annotations

import importlib
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from agentaudit.core.config import CallableSpec, HTTPSpec, TargetConfig
from agentaudit.core.egress import ValidatedEndpoint

_HTTPX_REQUEST_KWARGS = {"json", "params", "data", "content"}
_INPUT_PLACEHOLDER = "{{ input }}"


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
        if template == _INPUT_PLACEHOLDER:
            return input
        if _INPUT_PLACEHOLDER in template:
            return template.replace(_INPUT_PLACEHOLDER, str(input))
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
    def __init__(
        self,
        spec: HTTPSpec,
        endpoint: ValidatedEndpoint | None = None,
        transport: Any = None,
    ):
        self.spec = spec
        # None means egress policy was not applied -- only the local test stub
        # transport path, which never leaves the process. A hosted run always
        # carries a ValidatedEndpoint; see build_agent.
        self.endpoint = endpoint
        # Test seam only: an httpx transport to route through instead of the
        # network. Never set on a hosted run.
        self.transport = transport

    def run(self, input: str | dict) -> AgentResponse:
        spec = self.spec
        rendered = _render_template(spec.request, input)
        kwargs = {k: v for k, v in rendered.items() if k in _HTTPX_REQUEST_KWARGS}

        url = spec.endpoint
        headers = dict(spec.headers)
        extensions: dict[str, str] = {}
        if self.endpoint is not None:
            # Dial the address validated at run start, not the name. Resolving
            # again here is the rebinding window this exists to close.
            url = self.endpoint.pinned_url
            headers["Host"] = self.endpoint.host_header
            extensions["sni_hostname"] = self.endpoint.host

        start = time.perf_counter()
        try:
            # Client, not httpx.request: only Client.request accepts `extensions`,
            # which carries the SNI hostname for the pinned-address dial below.
            with httpx.Client(
                timeout=spec.timeout_s,
                # Redirects are off: a 302 to 169.254.169.254 would bypass every
                # check above. Supporting them means re-running the whole policy
                # on each hop, which is not worth it until a partner needs it.
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = client.request(
                    spec.method,
                    url,
                    headers=headers,
                    extensions=extensions,
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


class AttackerUnavailable(Exception):
    """The attacker model could not be reached or did not answer usably."""


class HTTPAttacker:
    """An OpenAI-compatible chat-completions client for the attacker model.

    Lives here rather than beside the rest of `core/attacker.py` for one
    reason: `httpx` is imported in this module alone, and that boundary is
    what makes the network surface auditable. `core/attacker.py` owns the
    refinement logic and never learns how the model is reached.

    OpenAI-compatible rather than provider-specific because every candidate
    backend (OpenAI, Anthropic via proxy, vLLM, Ollama) speaks this shape, and
    the alternative is an SDK dependency for a single POST.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        transport: Any = None,
        # Attackers want variance -- identical retries against the same refusal
        # are wasted turns. A judge wants the opposite: the same reply should
        # get the same verdict, so callers scoring rather than attacking pass 0.
        temperature: float = 0.9,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.transport = transport
        self.temperature = temperature

    def complete(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
                response = client.post(self.endpoint, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise AttackerUnavailable(f"attacker model unreachable: {exc}") from exc

        if response.is_error:
            raise AttackerUnavailable(
                f"attacker model returned http {response.status_code}"
            )
        try:
            body = response.json()
            return body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AttackerUnavailable(f"malformed attacker model response: {exc}") from exc


def build_agent(
    config: TargetConfig,
    sandbox: Any = None,
    endpoint: ValidatedEndpoint | None = None,
) -> Agent:
    agent_spec = config.agent
    if isinstance(agent_spec, CallableSpec):
        module_path, _, attr = agent_spec.callable.partition(":")
        module = importlib.import_module(module_path)
        factory = getattr(module, attr)
        fn = factory()
        return CallableAgent(fn, sandbox=sandbox)
    if isinstance(agent_spec, HTTPSpec):
        return HTTPAgent(agent_spec, endpoint=endpoint)
    raise ValueError(f"unknown agent spec type: {type(agent_spec)!r}")
