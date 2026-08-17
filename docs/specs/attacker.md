# feat/attacker — Spec

**Files:** `agentaudit/core/attacker.py`, `agentaudit/core/agent.py` (`HTTPAttacker`),
`tests/test_attacker.py`, `agentaudit/packs/core/jailbreak/refined_pressure.yaml`

## Goal

Close the one gap the scripted ladders in `core/adaptive.py` cannot: a ladder sends rung
*N* regardless of what the agent said back. This adds an attacker model that reads the
transcript and writes the next turn against the refusal actually received.

This is the "attacker-LLM strategy would slot in behind the same protocol" seam that
`adaptive.py` reserved, now filled. It is the only part of deepteam worth importing —
the rest was either already covered here or inseparable from `deepeval`.

## Public API

```python
class AttackerModel(Protocol):
    def complete(self, system: str, user: str) -> str: ...   # raises AttackerError

class RefinementLog:
    model_written: list[str]     # turns the model actually wrote
    fallbacks: list[str]         # why each fallback happened
    degraded: bool               # any fallback occurred

class RefiningStrategy:          # satisfies adaptive.AttackStrategy
    def __init__(goal, spec, model, redactor=None, log=None): ...
    def next_turn(history: list[AgentResponse]) -> str | None: ...

class HTTPAttacker:              # lives in core/agent.py, see below
    def __init__(endpoint, model, api_key=None, timeout_s=30.0, transport=None): ...

def build_attacker(spec) -> AttackerModel | None
def build_refining_strategy(goal, spec, model=None, log=None) -> AttackStrategy | None
```

Schema additions on `AdaptiveSpec`:

| field | default | meaning |
| --- | --- | --- |
| `refine` | `False` | Let an attacker model write each turn. |
| `refine_from` | `None` | Ladder supplying budget + fallback; defaults to `strategy`. |

## Configuration

Refinement activates only when **both** are true: `refine: true` on the test, and
`AGENTAUDIT_ATTACKER_ENDPOINT` + `AGENTAUDIT_ATTACKER_MODEL` set in the environment.
`AGENTAUDIT_ATTACKER_API_KEY` is optional.

Credentials come from the process environment, never from target config: a target file is
partner-supplied, and letting it name its own credential env var would be an exfiltration
primitive.

## Design decisions

- **The ladder is retained, not replaced.** `RefiningStrategy` wraps a ladder and asks it
  first, so `max_turns`, ladder length and `stop_on` still bound a refining run exactly
  like a scripted one. Refinement changes *what* is sent, never *how many*.
- **Failure degrades, it does not crash.** A rate limit, refusal, timeout or malformed
  reply falls back to the scripted rung. A red-team run that dies mid-suite because a
  third-party API hiccuped is worse than one that probes slightly less well.
- **Degradation is recorded.** `RefinementLog.degraded` exists so a report can never imply
  a model-driven probe happened when the run silently fell back to the script.
- **Replies are redacted before leaving the process.** The attacker model is a third-party
  endpoint and the agent's replies are evidence, so `redact_text` runs on the transcript
  first. The default is a builtins-on `Redactor`, because the failure mode of passing
  nothing must be the safe one. `tests/test_attacker.py` mutation-checks this.
- **The first turn is always scripted.** With no history there is nothing to react to, so
  a model call there would spend money for no signal.
- **`HTTPAttacker` lives in `core/agent.py`.** `httpx` is imported in exactly one module,
  and that boundary is what makes the network surface auditable. `core/attacker.py` owns
  the refinement logic and never learns how the model is reached.
  `tests/test_security_p0.py::test_httpx_is_imported_in_exactly_one_core_module`
  now enforces this instead of leaving it to a docs rule.
- **OpenAI-compatible, not provider-specific.** Every candidate backend (OpenAI, Anthropic
  via proxy, vLLM, Ollama) speaks that shape; the alternative is an SDK dependency for a
  single POST.

## What was deliberately not ported

deepteam's `LinearJailbreaking` is ~450 lines per attack, duplicated sync/async, and each
attack re-implements the same loop. The mechanism reduces to "ask a model for the next
turn", which is what this module does once for every ladder. Also skipped: its
`BehaviorShiftDetector` and `NonRefusal` judge (each an extra model call per turn, and
`stop_on` already covers the common case), the `deepeval` metric stack, and the
Confident AI API client.

## Testing

`tests/test_attacker.py` — 18 tests. The load-bearing ones: fallback on every failure
mode, redaction before egress, bounding preserved under refinement, and off-by-default so
CI stays offline and free. All use a stub attacker or `httpx.MockTransport`; no test
makes a network call.
