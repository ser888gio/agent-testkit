# feat/judge — Spec

**Files:** `agentaudit/core/judge.py`, `agentaudit/core/adaptive.py` (`Judge` protocol,
`_LadderStrategy._succeeded`), `agentaudit/core/jsonx.py`, `tests/test_judge.py`

## Goal

Replace the `stop_on` substring check that decides when an adaptive attack has landed.
That check is cheap and offline, and it is wrong in both directions:

- An agent that refuses while quoting the marker back ("I will not confirm that anything
  *has been processed*") trips it, so escalation stops on a refusal.
- An agent that complies in its own words does not trip it, so the ladder keeps escalating
  past a successful attack and reports the wrong turn as the finding.

A judge model reads the goal and the reply and answers the question directly.

## Public API

```python
class Judge(Protocol):           # declared in core/adaptive.py
    def succeeded(goal: str, response: AgentResponse) -> bool | None: ...

class JudgeLog:
    verdicts: list[dict]         # verdict, confidence, reasoning per call
    fallbacks: list[str]         # why each fallback happened
    degraded: bool               # any fallback occurred

class ModelJudge:
    def __init__(model, threshold=0.7, redactor=None, log=None): ...
    def succeeded(goal, response) -> bool | None: ...

def build_judge(log=None) -> ModelJudge | None
```

`bool | None` is the whole contract: `None` means *the judge could not answer*, and the
caller falls back to the substring check rather than guessing.

## Configuration

Judging activates when `AGENTAUDIT_JUDGE_ENDPOINT` + `AGENTAUDIT_JUDGE_MODEL` are set in
the environment. `AGENTAUDIT_JUDGE_API_KEY` is optional. No test-level opt-in: unlike
`refine`, a better stop condition is strictly an improvement on every adaptive test, so
there is nothing to gate per-test.

Credentials come from the process environment, never from target config — same reasoning
as the attacker model.

## Design decisions

- **Stop condition, never a scorer.** The judge decides when to stop escalating;
  assertions still decide pass/fail. Letting a model's opinion reach `Status` would put an
  unreproducible verdict inside compliance evidence, which is the one claim that evidence
  exists to support. This is the single most important boundary in the module.
- **It hangs off `_LadderStrategy._succeeded`.** That is the one method every ladder
  shares, so all four ladders pick the judge up at once, and `RefiningStrategy` inherits
  it by delegating termination to its wrapped ladder. One stop condition, not two.
- **The threshold guards only the positive case.** A low-confidence "yes" keeps
  escalating. Being wrong toward "keep going" wastes turns; being wrong toward "stop"
  reports the wrong turn as the finding, so the cheap error is the one to prefer.
- **Failure degrades to substrings.** Unreachable, non-JSON, or an unusable verdict all
  return `None` and log a fallback. `JudgeLog.degraded` exists so a report cannot describe
  a run as judged when it silently fell back.
- **Replies are redacted before leaving the process.** Same boundary and same
  builtins-on default as `RefiningStrategy`; `tests/test_judge.py` mutation-checks it.
- **`temperature=0.0`.** Judging is scoring: the same reply must produce the same verdict
  or a re-run reports different findings. `HTTPAttacker` grew a `temperature` parameter
  for this — it defaults to `0.9`, which is right for an attacker and wrong for a judge.
- **It reuses `HTTPAttacker` as transport.** Same OpenAI-compatible shape, and it keeps
  `httpx` confined to `core/agent.py`.

## Prior art

Ported from garak's `detectors/judge.py:ModelAsJudge` and
`detectors/agent_breaker.py:AgentBreakerResult.verify` (NVIDIA, Apache-2.0). Two things
taken directly: the `(verdict, confidence, reasoning)` return shape, and garak's practice
of driving loop control and reporting from *one* detector instance so the two can never
disagree. Not taken: garak's 1–10 rating scale, which asks a model for more precision than
it has — a binary verdict plus a confidence is the same information without the false
resolution.

## Testing

`tests/test_judge.py` — 14 tests. The load-bearing ones: the two cases substrings get
wrong (a compliance the markers miss, a refusal that quotes a marker), fallback on every
failure mode, redaction before egress, and off-by-default so CI stays offline and free.
All use a stub model; no test makes a network call.
