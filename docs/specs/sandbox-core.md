# feat/sandbox-core — Spec

**Task 6 · Depends on: 1 · Files:** `agentkit/core/sandbox.py`, `tests/test_sandbox_core.py`

## Goal
Generic sandbox behavior separated from any domain, so action-safety works for every vertical.

## Public API
```python
@dataclass
class Event:
    kind: str                    # e.g. "payment.created", "mail.sent"
    data: dict[str, Any]
    ts: datetime

class Sandbox(ABC):
    def reset(self) -> None                     # clear all state + events; call before each test
    def apply_setup(self, setup: dict) -> None  # seed state from TestCase.setup; domain-defined
    def snapshot(self) -> dict                   # deep, JSON-serializable state
    def diff(self, before: dict, after: dict) -> dict   # {"added":{}, "removed":{}, "changed":{}}
    @property
    def events(self) -> list[Event]
    def record_event(self, kind: str, data: dict) -> None
    @property
    def name(self) -> str        # registry key, e.g. "treasury"

SANDBOXES: dict[str, type[Sandbox]]     # registry
def register_sandbox(name): ...          # class decorator
def build_sandbox(name: str) -> Sandbox
```

## Behavior
- `reset()` must return the sandbox to a clean, deterministic zero-state (empty events).
- `snapshot()` returns plain dicts/lists/scalars only (must survive `json.dumps`).
- `diff(before, after)`: keys present only in after → `added`; only in before → `removed`;
  present in both but unequal → `changed` as `{key: {"before":…, "after":…}}`. Recurse one
  level into nested dicts for readability; deeper diffs may be shallow-compared.
- `record_event` appends with `ts=now(UTC)`; the demo agents call it whenever they take an
  action (this is the side-effect trail assertions and the UI read).

## Failure behavior
- `apply_setup` with an unknown key → `ValueError("sandbox 'name' cannot apply setup key 'k'")`.
- `build_sandbox("unknown")` → `KeyError`-style error listing registered names.

## Examples
```python
class Counter(Sandbox):  # test double
    ...
sb = Counter(); sb.reset()
before = sb.snapshot(); sb.record_event("inc", {"n": 1}); after = sb.snapshot()
sb.diff(before, after)   # {"added": {...}, "removed": {}, "changed": {...}}
len(sb.events)           # 1
```

## Tests required
- With an in-memory test sandbox: `reset` clears state+events; `snapshot` is JSON-serializable;
  `diff` correctly classifies added/removed/changed; `record_event` timestamps + orders.
- Registry: `register_sandbox` + `build_sandbox` round-trip; unknown name errors.

## Done when
A `Sandbox` subclass can seed state, record side-effects, snapshot, and produce a
before/after diff — with no treasury/email specifics in `core/sandbox.py`.
