import json
import subprocess
import sys

import pytest

from agentaudit.core.sandbox import (
    SANDBOXES,
    Sandbox,
    build_sandbox,
    register_sandbox,
)


class Counter(Sandbox):
    def __init__(self):
        super().__init__()
        self.n = 0

    def reset(self) -> None:
        self.n = 0
        self._clear_events()

    def apply_setup(self, setup: dict) -> None:
        for key, value in setup.items():
            if key != "n":
                raise self._unknown_setup_key(key)
            self.n = value

    def snapshot(self) -> dict:
        return {"n": self.n}

    def inc(self, by: int = 1) -> None:
        self.n += by
        self.record_event("inc", {"by": by})


def test_reset_clears_state_and_events():
    sb = Counter()
    sb.inc()
    sb.reset()
    assert sb.n == 0
    assert sb.events == []


def test_snapshot_is_json_serializable():
    sb = Counter()
    sb.inc(3)
    json.dumps(sb.snapshot())  # must not raise


def test_diff_classifies_added_removed_changed():
    sb = Counter()
    before = {"a": 1, "b": 2}
    after = {"b": 3, "c": 4}
    diff = sb.diff(before, after)
    assert diff["added"] == {"c": 4}
    assert diff["removed"] == {"a": 1}
    assert diff["changed"] == {"b": {"before": 2, "after": 3}}


def test_record_event_timestamps_and_orders():
    sb = Counter()
    sb.inc(1)
    sb.inc(2)
    assert len(sb.events) == 2
    assert sb.events[0].kind == "inc"
    assert sb.events[0].ts <= sb.events[1].ts
    assert sb.events[1].data == {"by": 2}


def test_apply_setup_seeds_state():
    sb = Counter()
    sb.apply_setup({"n": 5})
    assert sb.n == 5


def test_apply_setup_unknown_key_raises():
    sb = Counter()
    with pytest.raises(ValueError, match="cannot apply setup key 'bogus'"):
        sb.apply_setup({"bogus": 1})


def test_register_and_build_sandbox_round_trip():
    @register_sandbox("counter-test")
    class RegisteredCounter(Counter):
        pass

    try:
        sb = build_sandbox("counter-test")
        assert isinstance(sb, RegisteredCounter)
        assert sb.name == "counter-test"
    finally:
        del SANDBOXES["counter-test"]


def test_build_unknown_sandbox_raises():
    with pytest.raises(KeyError, match="unknown sandbox 'nope'"):
        build_sandbox("nope")


def test_the_registry_loads_its_own_builtins():
    """A fresh interpreter that never imported a domain still gets the built-ins.

    Run out of process on purpose: in-process another test's import would have
    filled the registry already, which is exactly the accident this replaces.
    """
    code = (
        "from agentaudit.core.sandbox import build_sandbox, sandbox_modules;"
        "print(build_sandbox('treasury').name);"
        "print(','.join(sandbox_modules()))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    name, modules = proc.stdout.split()
    assert name == "treasury"
    # What the spawned child imports to see the same registry.
    assert "agentaudit.domains.treasury.sandbox" in modules.split(",")
