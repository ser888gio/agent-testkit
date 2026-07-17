"""Execution lifecycle: target + tests -> RunResult, never crashing."""

from __future__ import annotations

import concurrent.futures
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from agentkit.core.agent import Agent, AgentResponse, build_agent
from agentkit.core.assertions import AssertionContext, evaluate
from agentkit.core.config import TargetConfig
from agentkit.core.loader import PythonTestCase
from agentkit.core.redaction import EvidencePolicy, Redactor
from agentkit.core.sandbox import Sandbox, build_sandbox
from agentkit.core.schema import (
    AssertionResult,
    RunResult,
    Status,
    TestCase,
    TestResult,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_with_timeout(
    agent: Agent, input: str | dict, timeout_s: float
) -> AgentResponse:
    # ponytail: Python has no thread-kill primitive, so a timed-out agent.run
    # keeps running in the background until it returns on its own (harmless for
    # process exit - the worker thread doesn't block shutdown - but it does mean
    # a hung agent leaks one thread/socket per timeout in a long-lived process
    # like `agentkit ui`). Revisit with cooperative cancellation (e.g. requiring
    # agents to accept a cancellation token) if that leak becomes real.
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="agentkit-agent"
    )
    future = executor.submit(agent.run, input)
    try:
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        return AgentResponse(error="timeout")
    finally:
        executor.shutdown(wait=False)


def _derive_status(
    response: AgentResponse, assertion_results: list[AssertionResult], test: TestCase
) -> Status:
    if response.error is not None:
        return Status.error
    if "skip" in test.tags or not test.assertions:
        return Status.skipped
    if all(r.passed for r in assertion_results):
        return Status.passed
    return Status.failed


def _redact_evidence(
    evidence: EvidencePolicy, redactor: Redactor, request: Any, response: AgentResponse
) -> tuple[Any, Any]:
    request_evidence = redactor.redact(request) if evidence.store_request else None
    if evidence.store_response:
        response_payload = {
            "text": response.text,
            "raw": response.raw,
            "status_code": response.status_code,
            "error": response.error,
        }
        response_evidence = redactor.redact(response_payload)
    else:
        response_evidence = None
    return request_evidence, response_evidence


def _redact_assertions(
    redactor: Redactor, results: list[AssertionResult]
) -> list[AssertionResult]:
    # Assertion details can echo response text or sandbox values, so they are
    # part of the evidence envelope and must be redacted before storage.
    return [
        r.model_copy(update={"detail": redactor.redact_text(r.detail)})
        for r in results
    ]


def run_one(
    agent: Agent,
    sandbox: Sandbox | None,
    test: TestCase,
    redactor: Redactor,
    evidence: EvidencePolicy | None = None,
) -> TestResult:
    evidence = evidence or EvidencePolicy()
    started = _now()
    try:
        if sandbox is not None:
            sandbox.reset()
            sandbox.apply_setup(test.setup)
            before = sandbox.snapshot()
        else:
            before = None

        # Single-input tests run one turn; multi-turn tests run each turn in
        # sequence WITHOUT resetting the sandbox between turns, so state (and
        # any poisoned memory) carries across turns like a server-side session.
        # The final turn's response is what assertions run against.
        turns = test.turns if test.turns else [test.input]
        for turn in turns:
            response = _run_with_timeout(agent, turn, test.timeout_s)
            if response.error == "timeout":
                break

        if sandbox is not None and response.error != "timeout":
            after = sandbox.snapshot()
            diff = sandbox.diff(before, after)
        else:
            # On timeout the worker thread keeps running and may still be
            # mutating the sandbox, so the diff is not trustworthy evidence.
            # See MERGED-PLAN.md §0a; killable isolation is Phase 2.
            # ponytail: thread-cancel is best-effort on CPython.
            diff = None

        ctx = AssertionContext(
            response=response,
            sandbox=sandbox,
            latency_ms=response.latency_ms,
            diff=diff,
        )
        assertion_results = [evaluate(a, ctx) for a in test.assertions]
        status = _derive_status(response, assertion_results, test)
        request = test.turns if test.turns else test.input
        request_evidence, response_evidence = _redact_evidence(
            evidence, redactor, request, response
        )

        return TestResult(
            test_id=test.id,
            category=test.category,
            risk=test.risk,
            status=status,
            latency_ms=response.latency_ms,
            assertion_results=_redact_assertions(redactor, assertion_results),
            request=request_evidence,
            response=response_evidence,
            sandbox_diff=redactor.redact(diff) if diff is not None else None,
            error=redactor.redact_text(response.error) if response.error else None,
            started_at=started,
            finished_at=_now(),
        )
    except Exception as exc:  # noqa: BLE001 - runner must never raise
        return TestResult(
            test_id=test.id,
            category=test.category,
            risk=test.risk,
            status=Status.error,
            latency_ms=None,
            assertion_results=[],
            request=None,
            response=None,
            sandbox_diff=None,
            error=str(exc),
            started_at=started,
            finished_at=_now(),
        )


def _run_python_test(
    agent: Agent,
    sandbox: Sandbox | None,
    test: PythonTestCase,
    redactor: Redactor,
    evidence: EvidencePolicy,
) -> TestResult:
    started = _now()
    try:
        if sandbox is not None:
            sandbox.reset()

        t0 = time.perf_counter()
        error: str | None = None
        try:
            test.fn(agent, sandbox)
            passed, detail = True, ""
        except AssertionError as exc:
            passed, detail = False, str(exc)
        latency_ms = (time.perf_counter() - t0) * 1000

        status = Status.passed if passed else Status.failed
        assertion_results = _redact_assertions(
            redactor, [AssertionResult(name=test.id, passed=passed, detail=detail)]
        )
        request_evidence, response_evidence = _redact_evidence(
            evidence, redactor, "<python test>", AgentResponse(text="", error=error)
        )

        return TestResult(
            test_id=test.id,
            category=test.category,
            risk=test.risk,
            status=status,
            latency_ms=latency_ms,
            assertion_results=assertion_results,
            request=request_evidence,
            response=response_evidence,
            sandbox_diff=None,
            error=redactor.redact_text(error) if error else None,
            started_at=started,
            finished_at=_now(),
        )
    except Exception as exc:  # noqa: BLE001 - runner must never raise
        return TestResult(
            test_id=test.id,
            category=test.category,
            risk=test.risk,
            status=Status.error,
            latency_ms=None,
            assertion_results=[],
            request=None,
            response=None,
            sandbox_diff=None,
            error=str(exc),
            started_at=started,
            finished_at=_now(),
        )


def run(
    target: TargetConfig,
    tests: list[TestCase | PythonTestCase],
    *,
    redactor: Redactor | None = None,
) -> RunResult:
    redactor = redactor or Redactor(target.evidence.redact)
    sandbox = build_sandbox(target.sandbox) if target.sandbox else None
    agent = build_agent(target, sandbox=sandbox)

    started = _now()
    results: list[TestResult] = []
    for test in tests:
        if isinstance(test, PythonTestCase):
            results.append(
                _run_python_test(agent, sandbox, test, redactor, target.evidence)
            )
        else:
            results.append(run_one(agent, sandbox, test, redactor, target.evidence))

    return RunResult(
        run_id=uuid.uuid4().hex,
        agent_name=target.id,
        started_at=started,
        finished_at=_now(),
        results=results,
    )
