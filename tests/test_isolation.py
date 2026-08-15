import sys
import time
from types import SimpleNamespace

from agentkit.core.assertions import AssertionContext, assertion
from agentkit.core.config import CallableSpec, TargetConfig
from agentkit.core.isolation import _apply_posix_limits
from agentkit.core.runner import run
from agentkit.core.sandbox import Sandbox, register_sandbox
from agentkit.core.schema import Assertion, AssertionResult, Category, TestCase

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
