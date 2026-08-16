"""Execution lifecycle: target + tests -> RunResult, never crashing."""

from __future__ import annotations

import concurrent.futures
import math
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from agentaudit.core import isolation
from agentaudit.core.adaptive import build_strategy
from agentaudit.core.agent import Agent, AgentResponse
from agentaudit.core.assertions import AssertionContext, evaluate
from agentaudit.core.config import TargetConfig
from agentaudit.core.egress import ValidatedEndpoint
from agentaudit.core.isolation import IsolatedRunner, IsolationFailure
from agentaudit.core.loader import PythonTestCase
from agentaudit.core.redaction import EvidencePolicy, Redactor
from agentaudit.core.sandbox import SANDBOXES, Sandbox
from agentaudit.core.schema import (
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
    # Legacy/direct run_one path. Production run() supplies the nested
    # process-backed turn runner instead; this fallback cannot kill its thread,
    # so run_one deliberately discards its timeout diff.
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="agentaudit-agent"
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


def _run_turns(
    agent: Agent | None,
    test: TestCase,
    run_turn: Callable[[Any, float], AgentResponse] | None,
) -> tuple[AgentResponse, Any]:
    # Single-input tests run one turn; multi-turn tests run each turn in
    # sequence WITHOUT resetting the sandbox between turns, so state (and
    # any poisoned memory) carries across turns like a server-side session.
    # The final turn's response is what assertions run against.
    #
    # Returns the final response plus the turns actually sent, because an
    # adaptive test's turns are generated here and are the only record of them.
    def _send(turn: Any) -> AgentResponse:
        if run_turn is None:
            if agent is None:  # pragma: no cover - internal invariant
                raise ValueError("agent is required without an isolated turn runner")
            return _run_with_timeout(agent, turn, test.timeout_s)
        return run_turn(turn, test.timeout_s)

    if test.adaptive is not None:
        strategy = build_strategy(test.input, test.adaptive)
        history: list[AgentResponse] = []
        sent: list[Any] = []
        while (turn := strategy.next_turn(history)) is not None:
            sent.append(turn)
            response = _send(turn)
            history.append(response)
            if response.error == "timeout":
                break
        return history[-1], sent

    turns = test.turns if test.turns else [test.input]
    for turn in turns:
        response = _send(turn)
        if response.error == "timeout":
            break
    return response, (test.turns if test.turns else test.input)


def run_one(
    agent: Agent | None,
    sandbox: Sandbox | None,
    test: TestCase,
    redactor: Redactor,
    evidence: EvidencePolicy | None = None,
    *,
    run_turn: Callable[[Any, float], AgentResponse] | None = None,
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

        response, request = _run_turns(agent, test, run_turn)

        # An isolated turn runner kills the agent worker before returning a
        # timeout, so the supervisor-owned sandbox is stable.  Direct calls to
        # run_one retain the conservative legacy behavior because their thread
        # cannot be killed.
        stable_timeout = response.error != "timeout" or run_turn is not None
        if sandbox is not None and stable_timeout:
            after = sandbox.snapshot()
            diff = sandbox.diff(before, after)
        else:
            diff = None

        ctx = AssertionContext(
            response=response,
            sandbox=sandbox,
            latency_ms=response.latency_ms,
            diff=diff,
            calls=sandbox.events if sandbox is not None else [],
        )
        assertion_results = [evaluate(a, ctx) for a in test.assertions]
        status = _derive_status(response, assertion_results, test)
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
        return _error_result(test, started, str(exc), redactor)


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
        return _error_result(test, started, str(exc), redactor)


def _error_result(
    test: TestCase | PythonTestCase,
    started: datetime,
    error: str,
    redactor: Redactor,
) -> TestResult:
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
        error=redactor.redact_text(error),
        started_at=started,
        finished_at=_now(),
    )


def _sandbox_modules() -> tuple[str, ...]:
    # Pass registered sandbox module names to the spawned interpreter. Named,
    # not imported, so core keeps no dependency edge to domain packages while
    # third-party Sandbox registrations work too.
    modules = {sandbox_type.__module__ for sandbox_type in SANDBOXES.values()}
    modules.update(
        name for name in list(sys.modules) if name.startswith("agentaudit.domains.")
    )
    return tuple(sorted(modules))


def _run_isolated(
    isolated: IsolatedRunner,
    test: TestCase | PythonTestCase,
    redactor: Redactor,
) -> TestResult:
    test_started = _now()
    if isinstance(test, PythonTestCase):
        if not math.isfinite(test.timeout_s) or test.timeout_s <= 0:
            result: TestResult | IsolationFailure = IsolationFailure(
                "timeout_s must be finite and > 0"
            )
        else:
            result = isolated.run_python_test(
                test, test.timeout_s + isolation.GRACE_SECONDS
            )
    else:
        if test.adaptive is not None:
            turns = test.adaptive.max_turns
        else:
            turns = len(test.turns) if test.turns else 1
        result = isolated.run_test(
            test, turns * test.timeout_s + isolation.GRACE_SECONDS
        )
    if isinstance(result, IsolationFailure):
        result = _error_result(test, test_started, result.error, redactor)
    return result


def _repeat_count(test: TestCase | PythonTestCase) -> int:
    return getattr(test, "repeat", 1)


def _fold_attempts(attempts: list[TestResult]) -> TestResult:
    """pass^k: one result standing for k attempts, passing only if all k passed."""
    statuses = [a.status for a in attempts]
    # Report the first non-passing attempt, so the evidence explains the verdict.
    representative = next((a for a in attempts if a.status is not Status.passed), attempts[-1])
    return representative.model_copy(update={"attempts": statuses})


def run(
    target: TargetConfig,
    tests: list[TestCase | PythonTestCase],
    *,
    redactor: Redactor | None = None,
    endpoint: ValidatedEndpoint | None = None,
) -> RunResult:
    """`endpoint` carries the egress decision made at run start.

    It is passed in rather than computed here because validation needs the
    target's allowlist, which is a Store concern the runner must not reach into.

    YAML and Python tests execute in a killable child process
    (`core/isolation.py`). Python functions are serialized into the child; the
    tested agent itself runs in a nested worker so it can be killed before the
    sandbox owner snapshots timeout evidence.
    """
    redactor = redactor or Redactor(target.evidence.redact)
    isolated = IsolatedRunner(target, redactor, endpoint, _sandbox_modules())

    started = _now()
    results: list[TestResult] = []
    try:
        for test in tests:
            repeat = _repeat_count(test)
            attempts = [_run_isolated(isolated, test, redactor) for _ in range(repeat)]
            results.append(attempts[0] if repeat == 1 else _fold_attempts(attempts))
    finally:
        isolated.close()

    return RunResult(
        run_id=uuid.uuid4().hex,
        agent_name=target.id,
        started_at=started,
        finished_at=_now(),
        results=results,
    )
