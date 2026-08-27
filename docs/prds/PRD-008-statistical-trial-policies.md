# PRD-008 — Statistical trial policies for gating (k≥3 with pass thresholds)

**Type:** Feature · **Status:** Proposed

## Problem
Every agentaudit gate is one sample of a nondeterministic distribution. Practitioners
report that single-run verdicts on agents are noise: the 95% CI on a measured pass rate is
~±14% at one run vs ~±3% at three, so single-run CI "buys almost none" of the certainty
([dreaming.press](https://dreaming.press/posts/how-to-test-a-non-deterministic-ai-agent.html));
the same conclusion from distributed-systems practice (pass^k as the reliability metric,
[saumilsrivastava.ai](https://www.saumilsrivastava.ai/blog/agent-evaluation-is-a-distributed-systems-problem)).
RAMPART — the closest competitor — ships `@pytest.mark.trial(n=10, threshold=0.8)`
natively ([CI docs](https://microsoft.github.io/RAMPART/usage/ci-integration/)). AgentAudit's
runner already folds `repeat` attempts via pass^k (`core/runner.py:_fold_attempts`) but it
defaults to 1, no pack sets it, and there is no threshold policy or cost control. Repo
PRD-004 (tiered gating/flake quarantine) is related but scopes flake handling; this PRD
scopes per-test statistical policies and their defaults.

## Proposed solution
- Pack-level/test-level `trial:` policy in YAML (`n`, `threshold`, e.g. safe in ≥80% of n runs),
  compiled onto the existing `repeat` + `_fold_attempts` machinery; extend folding to
  threshold semantics alongside strict pass^k.
- Sensible default policy for adaptive/multi-turn tests (e.g. n=3) with an opt-out;
  sequential early-stop when lower confidence bound already decides (cost control).
- Gate math reads trial results; reports show per-test n/pass-rate/threshold, and the token
  cost delta of the run.

## Success criteria
- A test failing 20% of the time passes under `trial(n=5, threshold=0.75)` and fails by default.
- Documented cost model; sequential stop demonstrably cuts repeat-run cost ≥50% on clear-cut cases.
- Docs steer users to trials for multi-turn packs; RAMPART-parity acknowledged in compare docs.

## Priority & effort
P0 — without it, gates are statistically indefensible and the competitor ships this today
· Effort: M

## Open questions
- Default n=3 for all tests or only adaptive/multi-turn? (Cost vs trust trade-off.)
- Does `agentaudit compare` treat a threshold-flip as a critical regression?
