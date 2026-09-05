"""Execution lifecycle: target + tests -> RunResult, never crashing."""

from __future__ import annotations

import concurrent.futures
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from agentaudit.core.adaptive import build_strategy
from agentaudit.core.agent import Agent, AgentResponse
from agentaudit.core.assertions import AssertionContext, evaluate
from agentaudit.core.attacker import RefinementLog, build_refining_strategy
from agentaudit.core.config import TargetConfig
from agentaudit.core.egress import ValidatedEndpoint
from agentaudit.core.isolation import IsolatedRunner, IsolationFailure
from agentaudit.core.judge import JudgeLog, build_judge
from agentaudit.core.loader import PythonTestCase
from agentaudit.core.redaction import EvidencePolicy, Redactor
from agentaudit.core.sandbox import Sandbox, sandbox_modules
from agentaudit.core.schema import (
    AssertionResult,
    RunResult,
    SandboxEvent,
    Status,
    TestCase,
    TestResult,
    TrialPolicy,
)

log = logging.getLogger("agentaudit.runner")


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


def _evidence_bearing(
    status: Status, assertion_results: list[AssertionResult]
) -> list[AssertionResult]:
    """Drop assertion rows for a status that means "no verdict was reached".

    ERROR and SKIPPED both mean the agent never produced a reply this run can
    reason about, but the assertions were still evaluated -- against
    `response.text == ""` for a timeout, or against a sandbox that was never
    exercised for a skip. Every negative assertion (`not_contains` and friends)
    passes vacuously there, and every positive one fails just as vacuously.
    Persisting those rows puts "timeout" and "pass" on the same step, which
    reads as a broken report and, worse, as evidence the agent was probed when
    it never answered.

    The status itself already carries the outcome -- `findings.FAILING` counts
    ERROR as a failure, so nothing about gating changes here. This only stops
    the run from claiming assertion-level evidence it does not have, the same
    rule `_skipped_result` already follows by shipping no assertion rows at all.
    """
    if status in (Status.error, Status.skipped):
        return []
    return assertion_results


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


def _redact_events(redactor: Redactor, events: list[Any]) -> list[SandboxEvent]:
    # `Event.data` can hold anything a domain sandbox chooses to record (e.g.
    # a payee/bank_details pair), so it goes through the same generic redactor
    # as sandbox_diff before it becomes evidence.
    return [
        SandboxEvent(kind=e.kind, data=redactor.redact(e.data), ts=e.ts) for e in events
    ]


@dataclass
class _Provenance:
    """How this run's turns were produced, for the evidence record.

    Empty for every scripted run. Carries names and a boolean only: the
    attacker's rationale and the judge's reasoning are derived from agent
    replies, so they stay out of anything persisted.
    """

    techniques: list[str] = field(default_factory=list)
    degraded: bool = False


def _run_turns(
    agent: Agent | None,
    test: TestCase,
    run_turn: Callable[[Any, float], AgentResponse] | None,
) -> tuple[AgentResponse, Any, _Provenance]:
    # Single-input tests run one turn; multi-turn tests run each turn in
    # sequence WITHOUT resetting the sandbox between turns, so state (and
    # any poisoned memory) carries across turns like a server-side session.
    # The final turn's response is what assertions run against.
    #
    # Returns the final response, the turns actually sent (an adaptive test's
    # turns are generated here and are the only record of them), and how they
    # were produced.
    def _send(turn: Any) -> AgentResponse:
        if run_turn is None:
            if agent is None:  # pragma: no cover - internal invariant
                raise ValueError("agent is required without an isolated turn runner")
            return _run_with_timeout(agent, turn, test.timeout_s)
        return run_turn(turn, test.timeout_s)

    if test.adaptive is not None:
        # Both model-driven layers are opt-in and return None when
        # unconfigured, so the scripted ladder with its substring stop check
        # stays the default path for every offline run. The logs are passed in
        # rather than left to default so what they record survives the call.
        refinement_log = RefinementLog()
        judge_log = JudgeLog()
        judge = build_judge(log=judge_log)
        strategy = build_refining_strategy(
            test.input, test.adaptive, log=refinement_log, judge=judge
        ) or build_strategy(test.input, test.adaptive, judge)
        history: list[AgentResponse] = []
        sent: list[Any] = []
        while (turn := strategy.next_turn(history)) is not None:
            sent.append(turn)
            response = _send(turn)
            history.append(response)
            if response.error == "timeout":
                break
        provenance = _Provenance(
            techniques=list(refinement_log.techniques),
            degraded=refinement_log.degraded or judge_log.degraded,
        )
        return history[-1], sent, provenance

    turns = test.turns if test.turns else [test.input]
    for turn in turns:
        response = _send(turn)
        if response.error == "timeout":
            break
    return response, (test.turns if test.turns else test.input), _Provenance()


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
        if test.setup and sandbox is None:
            # A test that needs seeded sandbox state has nothing to seed and no
            # sandbox for its assertions to inspect: neither the agent nor the
            # target config did anything wrong. Reporting this as SKIPPED (not
            # FAILED) keeps a sandbox-dependent test from fabricating a finding
            # against a target that simply has no sandbox configured.
            return _skipped_result(test, started, "requires sandbox, none configured")

        if sandbox is not None:
            sandbox.reset()
            sandbox.apply_setup(test.setup)
            before = sandbox.snapshot()
        else:
            before = None

        response, request, provenance = _run_turns(agent, test, run_turn)

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
        assertion_results = _evidence_bearing(status, assertion_results)
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
            events=_redact_events(redactor, ctx.calls),
            error=redactor.redact_text(response.error) if response.error else None,
            techniques=provenance.techniques,
            degraded=provenance.degraded,
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


def _skipped_result(test: TestCase, started: datetime, reason: str) -> TestResult:
    return TestResult(
        test_id=test.id,
        category=test.category,
        risk=test.risk,
        status=Status.skipped,
        latency_ms=None,
        assertion_results=[],
        request=None,
        response=None,
        sandbox_diff=None,
        error=reason,
        started_at=started,
        finished_at=_now(),
    )


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


def _run_isolated(
    isolated: IsolatedRunner,
    test: TestCase | PythonTestCase,
    redactor: Redactor,
) -> TestResult:
    test_started = _now()
    result: TestResult | IsolationFailure = (
        isolated.run_python_test(test)
        if isinstance(test, PythonTestCase)
        else isolated.run_test(test)
    )
    if isinstance(result, IsolationFailure):
        result = _error_result(test, test_started, result.error, redactor)
    return result


def _repeat_count(test: TestCase | PythonTestCase) -> int:
    return getattr(test, "repeat", 1)


def _trial_policy(test: TestCase | PythonTestCase) -> TrialPolicy | None:
    # PythonTestCase (a dataclass) has no trial support -- only YAML TestCase does.
    effective = getattr(test, "effective_trial", None)
    return effective() if effective is not None else None


def _decided(passed: int, ran: int, n: int, threshold: float) -> bool:
    """True if no possible outcome of the remaining `n - ran` attempts can
    change whether the final pass rate clears `threshold`.

    Exact best/worst-case bound, not a probabilistic estimate: the best case
    is every remaining attempt passing, the worst is every remaining attempt
    failing. If both land on the same side of `threshold`, more attempts
    cannot change the verdict, so running them is pure cost with no
    information value. This is what makes early-stop safe to apply
    unconditionally -- it never produces a different verdict than running
    all `n`.
    """
    remaining = n - ran
    best_rate = (passed + remaining) / n
    worst_rate = passed / n
    return (best_rate >= threshold) == (worst_rate >= threshold)


def _fold_attempts(attempts: list[TestResult], threshold: float = 1.0) -> TestResult:
    """One result standing for however many attempts ran.

    `threshold=1.0` (the default, and the only mode `repeat:` without a
    `trial:` policy ever uses) is strict pass^k: every attempt must pass.
    A lower threshold passes once the pass rate over `attempts` meets it --
    trial semantics. `attempts` may be shorter than the test's configured
    `n` when the caller stopped early via `_decided`.
    """
    statuses = [a.status for a in attempts]
    passed = sum(1 for s in statuses if s is Status.passed)
    pass_rate = passed / len(statuses)
    if pass_rate >= threshold and threshold < 1.0:
        # Trial policy cleared: pass, using the last attempt as the evidence
        # representative since there is no single "the" failing attempt.
        representative = attempts[-1]
        status = Status.passed
    else:
        # Strict pass^k (threshold == 1.0, including plain `repeat:`): the
        # first non-passing attempt decides both the status and the evidence,
        # exactly as before trial policies existed.
        representative = next((a for a in attempts if a.status is not Status.passed), attempts[-1])
        status = representative.status
    return representative.model_copy(
        update={
            "attempts": statuses,
            "status": status,
            "trial_threshold": None if threshold >= 1.0 else threshold,
        }
    )


def _run_trial(
    isolated: IsolatedRunner,
    test: TestCase | PythonTestCase,
    redactor: Redactor,
    policy: TrialPolicy,
) -> TestResult:
    attempts: list[TestResult] = []
    passed = 0
    for i in range(policy.n):
        result = _run_isolated(isolated, test, redactor)
        attempts.append(result)
        if result.status is Status.passed:
            passed += 1
        if _decided(passed, i + 1, policy.n, policy.threshold):
            break
    return _fold_attempts(attempts, policy.threshold)


def _with_target_timeout(
    target: TargetConfig, tests: list[TestCase | PythonTestCase]
) -> list[TestCase | PythonTestCase]:
    """Raise each test's execution ceiling to at least the target's timeout.

    A test's `timeout_s` is the wall-clock budget for one turn; the target's is
    the per-call budget the transport was configured with. A target declaring a
    60s call budget under tests carrying the 30s default would have every slow
    but legitimate call killed by the runner and recorded as ERROR -- a phantom
    timeout attributed to the agent. `max` rather than a plain override, so a
    test that deliberately asks for a *longer* budget keeps it, and a fast
    target cannot weaken a test's latency expectations.
    """
    ceiling = getattr(target.agent, "timeout_s", None)
    if ceiling is None:
        return tests
    raised: list[TestCase | PythonTestCase] = []
    for test in tests:
        if test.timeout_s >= ceiling:
            raised.append(test)
        elif isinstance(test, TestCase):
            raised.append(test.model_copy(update={"timeout_s": ceiling}))
        else:
            raised.append(replace(test, timeout_s=ceiling))
    return raised


def run(
    target: TargetConfig,
    tests: list[TestCase | PythonTestCase],
    *,
    redactor: Redactor | None = None,
    endpoint: ValidatedEndpoint | None = None,
    on_test: Callable[[int, TestCase | PythonTestCase], None] | None = None,
    on_result: Callable[[int, TestResult], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RunResult:
    """`endpoint` carries the egress decision made at run start.

    It is passed in rather than computed here because validation needs the
    target's allowlist, which is a Store concern the runner must not reach into.

    YAML and Python tests execute in a killable child process
    (`core/isolation.py`). Python functions are serialized into the child; the
    tested agent itself runs in a nested worker so it can be killed before the
    sandbox owner snapshots timeout evidence.

    `should_stop`, if given, is polled between tests. It stops the loop, not
    the run: everything completed so far is still returned as a `RunResult`,
    same as reaching the end of `tests` normally -- there is no cancelled
    variant of this return value, only a shorter `results` list. This is a
    separate control from `on_result`, which reports progress and is
    deliberately never allowed to affect whether the run continues.
    """
    redactor = redactor or Redactor(target.evidence.redact)
    tests = _with_target_timeout(target, tests)
    isolated = IsolatedRunner(target, redactor, endpoint, sandbox_modules())

    started = _now()
    results: list[TestResult] = []
    try:
        for index, test in enumerate(tests):
            if should_stop is not None and should_stop():
                break
            if on_test is not None:
                on_test(index, test)
            policy = _trial_policy(test)
            if policy is not None:
                result = _run_trial(isolated, test, redactor, policy)
            else:
                repeat = _repeat_count(test)
                attempts = [_run_isolated(isolated, test, redactor) for _ in range(repeat)]
                result = attempts[0] if repeat == 1 else _fold_attempts(attempts)
            results.append(result)
            if on_result is not None:
                # Progress reporting must never take the run down with it: the
                # evidence matters, a dropped status update does not.
                try:
                    on_result(index, result)
                except Exception:  # noqa: BLE001
                    log.warning("on_result callback failed for %s", test.id, exc_info=True)
    finally:
        isolated.close()

    return RunResult(
        run_id=uuid.uuid4().hex,
        agent_name=target.id,
        started_at=started,
        finished_at=_now(),
        results=results,
    )
