"""P0 fail-closed / security regression gates. See docs/archive/plans/MERGED-PLAN.md §0a.

Each test reproduces a weakness that the current code either had or could
regress into, and asserts the hardened behaviour.
"""

from __future__ import annotations

import time

from agentkit.core.agent import AgentResponse
from agentkit.core.loader import PythonTestCase
from agentkit.core.redaction import EvidencePolicy, RedactionConfig, Redactor
from agentkit.core.runner import _redact_assertions, _run_python_test, run_one
from agentkit.core.sandbox import Sandbox
from agentkit.core.schema import (
    Assertion,
    AssertionResult,
    Category,
    Risk,
    Status,
    TestCase,
)
from fastapi.testclient import TestClient

# --- scoring fails closed (covered in test_scoring.py::test_all_skipped_run_fails_closed)


# --- web run route: token required, paths outside allowlist rejected -------


def _web_client() -> TestClient:
    from agentkit.web.app import app

    return TestClient(app)


def test_post_runs_rejects_missing_token():
    client = _web_client()
    resp = client.post("/runs", params={"target": "x", "packs": "y"})
    assert resp.status_code == 403


def test_post_runs_rejects_path_outside_allowlist():
    from agentkit.web.app import _ACCESS_TOKEN

    client = _web_client()
    # A valid token but a target path escaping config/ and packs/ must be refused,
    # so the route can never load an arbitrary Python callable.
    resp = client.post(
        "/runs",
        params={
            "target": "/etc/passwd",
            "packs": "../../evil",
            "token": _ACCESS_TOKEN,
        },
    )
    assert resp.status_code == 400


# --- timeout must not yield a trusted sandbox diff -------------------------


class _SlowAgent:
    def run(self, input):  # noqa: A002 - mirror Agent signature
        time.sleep(0.5)
        return AgentResponse(text="done")


class _CountingSandbox(Sandbox):
    """Minimal sandbox whose snapshot changes over time, to prove that a
    post-timeout diff would be non-empty if we trusted it."""

    def __init__(self) -> None:
        self._n = 0

    def reset(self) -> None:
        self._n = 0

    def apply_setup(self, setup) -> None:  # noqa: ANN001
        pass

    def snapshot(self):
        self._n += 1
        return {"n": self._n}

    def diff(self, before, after):  # noqa: ANN001
        return {} if before == after else {"n": [before["n"], after["n"]]}


def test_timeout_does_not_produce_trusted_diff():
    redactor = Redactor(RedactionConfig())
    test = TestCase(
        id="t.timeout.case",
        category=Category.reliability,
        input="hi",
        timeout_s=0.05,
        assertions=[Assertion(name="status_ok")],
    )
    result = run_one(_SlowAgent(), _CountingSandbox(), test, redactor)
    assert result.status == Status.error
    assert result.error == "timeout"
    # The worker thread may still be mutating; the diff is not trustworthy.
    assert result.sandbox_diff is None


# --- redaction covers assertion details and error strings ------------------


def test_assertion_detail_is_redacted():
    redactor = Redactor(RedactionConfig())
    results = [
        AssertionResult(
            name="not_contains",
            passed=False,
            detail="response leaked sk-abcdefgh12345678 to the caller",
        )
    ]
    redacted = _redact_assertions(redactor, results)
    assert "sk-abcdefgh12345678" not in redacted[0].detail
    assert "redacted:api_key" in redacted[0].detail


class _FailingSandbox(_CountingSandbox):
    def reset(self) -> None:
        raise RuntimeError("sandbox failed with sk-abcdefgh12345678")


def test_runner_redacts_unexpected_exception_messages():
    test = TestCase(
        id="t.exception.case",
        category=Category.reliability,
        input="hi",
        assertions=[Assertion(name="status_ok")],
    )

    result = run_one(_SlowAgent(), _FailingSandbox(), test, Redactor(RedactionConfig()))

    assert result.status == Status.error
    assert "sk-abcdefgh12345678" not in result.error
    assert "redacted:api_key" in result.error


def test_python_runner_redacts_unexpected_exception_messages():
    test = PythonTestCase(
        id="python.exception.case",
        category=Category.reliability,
        risk=Risk.medium,
        fn=lambda agent, sandbox: None,
    )

    result = _run_python_test(
        _SlowAgent(),
        _FailingSandbox(),
        test,
        Redactor(RedactionConfig()),
        EvidencePolicy(),
    )

    assert result.status == Status.error
    assert "sk-abcdefgh12345678" not in result.error
    assert "redacted:api_key" in result.error
