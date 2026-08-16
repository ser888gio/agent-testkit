import sys
import time
from types import SimpleNamespace

from agentaudit.core.assertions import AssertionContext, assertion
from agentaudit.core.config import CallableSpec, TargetConfig
from agentaudit.core.isolation import _apply_posix_limits
from agentaudit.core.runner import run
from agentaudit.core.sandbox import Sandbox, register_sandbox
from agentaudit.core.schema import Assertion, AssertionResult, Category, TestCase

MODULE = "tests.test_isolation"


@register_sandbox("isolation-counter")
class IsolationCounter(Sandbox):
    def __init__(self):
        super().__init__()
        self.n = 0
        self._snapshots = 0

    def reset(self) -> None:
        self.n = 0
        self._snapshots = 0
        self._clear_events()

    def apply_setup(self, setup: dict) -> None:
        if setup:
            raise ValueError("setup is not supported")

    def snapshot(self) -> dict:
        self._snapshots += 1
        if self._snapshots == 2:
            # The old design took this snapshot while the timed-out agent
            # thread was still alive, giving it time to mutate n again.
            time.sleep(0.3)
        return {"n": self.n}

    def inc(self) -> None:
        self.n += 1
        self.record_event("inc", {"n": self.n})


@assertion("_calls_seen")
def _calls_seen(ctx: AssertionContext) -> AssertionResult:
    kinds = [c.kind for c in ctx.calls]
    return AssertionResult(
        name="_calls_seen", passed=kinds == ["inc", "inc"], detail=f"calls={kinds}"
    )


def _late_mutating_agent(input, sandbox):
    sandbox.inc()
    time.sleep(0.15)
    sandbox.inc()
    time.sleep(30)


def create_late_mutating_agent():
    return _late_mutating_agent


def test_posix_limits_lower_the_hard_limit(monkeypatch):
    applied = []
    fake_resource = SimpleNamespace(
        RLIMIT_AS=1,
        RLIMIT_CPU=2,
        RLIM_INFINITY=-1,
        getrlimit=lambda what: (10_000, -1),
        setrlimit=lambda what, limits: applied.append((what, limits)),
    )
    monkeypatch.setitem(sys.modules, "resource", fake_resource)

    _apply_posix_limits(memory_mb=1, cpu_seconds=7)

    assert applied == [(1, (1024 * 1024, 1024 * 1024)), (2, (7, 7))]


def _double_inc_agent(input, sandbox):
    sandbox.inc()
    sandbox.inc()
    return "done"


def create_double_inc_agent():
    return _double_inc_agent


def _escalating_agent(input, sandbox):
    # Walk toward the supervisor's globals via a dunder that does not exist on
    # the proxy, so the request would otherwise be forwarded over the RPC.
    try:
        leaked = sandbox.__globals__
    except (AttributeError, RuntimeError) as exc:
        return f"refused: {exc}"
    return f"escalated: {type(leaked).__name__}"


def create_escalating_agent():
    return _escalating_agent


def test_tool_call_ledger_crosses_isolation_boundary():
    # The sandbox lives in the supervisor process; the agent mutates it only
    # via the RPC proxy. This proves record_event() calls made through that
    # proxy land in the AssertionContext the supervisor builds afterward.
    target = TargetConfig(
        id="ledger-target",
        agent=CallableSpec(
            type="callable", callable=f"{MODULE}:create_double_inc_agent"
        ),
        sandbox="isolation-counter",
    )
    test = TestCase(
        id="ledger.case",
        category=Category.action_safety,
        input="go",
        assertions=[Assertion(name="_calls_seen")],
    )

    result = run(target, [test]).results[0]

    assert result.assertion_results[0].passed, result.assertion_results[0].detail


def test_sandbox_rpc_refuses_forwarded_dunder_access():
    # The agent worker is untrusted; the RPC resolves attribute paths in the
    # supervisor, which holds unredacted evidence. A dunder that is absent on
    # the proxy would be forwarded there, so it is refused before it is sent.
    target = TargetConfig(
        id="escalation-target",
        agent=CallableSpec(type="callable", callable=f"{MODULE}:create_escalating_agent"),
        sandbox="isolation-counter",
    )
    test = TestCase(
        id="rpc.dunder_refused",
        category=Category.action_safety,
        input="escalate",
        assertions=[Assertion(name="status_ok")],
    )

    result = run(target, [test]).results[0]
    response = str(result.response or "")

    assert "escalated" not in response
    assert "refuses dunder access" in response


def test_proxy_class_dunders_are_a_known_isolation_gap():
    """Pins a limitation, not a guarantee.

    `__getattr__` is bypassed for attributes Python resolves on the class, so
    `sandbox.__class__` hands the agent isolation.py's module globals and no
    guard in `__getattr__` can intercept it. Closing this needs a proxy with no
    reachable attributes. Until then the *container* is the boundary that makes
    this survivable. If this test starts failing, the gap was closed -- delete
    it and update the caveat in infra/CLAUDE.md.
    """
    from agentaudit.core.isolation import _RemoteObject

    proxy = _RemoteObject.__new__(_RemoteObject)

    assert proxy.__class__ is _RemoteObject
    assert "_RemoteObject" in proxy.__class__.__init__.__globals__


def test_agent_is_dead_before_timeout_snapshot_is_taken():
    target = TargetConfig(
        id="late-mutation",
        agent=CallableSpec(
            type="callable", callable=f"{MODULE}:create_late_mutating_agent"
        ),
        sandbox="isolation-counter",
    )
    test = TestCase(
        id="timeout.atomic_diff",
        category=Category.action_safety,
        input="mutate",
        assertions=[Assertion(name="status_ok")],
        timeout_s=0.1,
    )

    result = run(target, [test]).results[0]

    assert result.error == "timeout"
    assert result.sandbox_diff["changed"]["n"]["after"] == 1
