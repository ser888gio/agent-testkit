# Statistical Trial Policies — Design Note

**PRD-008 · Status: shipped**

## Goal

Every agentaudit gate is one sample of a nondeterministic agent's behavior. `repeat:`
already existed (`core/runner.py:_fold_attempts`) but only expressed strict pass^k — every
attempt must pass — with no pass-rate threshold and no cost control. This adds a `trial:`
policy (RAMPART's `@pytest.mark.trial(n, threshold)`, functionally) plus a sequential
early-stop so trials don't multiply run cost by `n` on clear-cut cases.

## Pack YAML

```yaml
id: treasury.flaky_tool.retry_tolerant
category: reliability
risk: medium
input: "Reconcile today's transactions."
assertions:
  - name: status_ok
trial:
  n: 5           # run up to 5 attempts (fewer if early-stop decides sooner)
  threshold: 0.75 # pass if >= 75% of attempts pass (>= 4 of 5)
```

`trial:` is optional and additive (`core/schema.py:TestCase.trial`). Omitting it leaves
today's behavior exactly unchanged:

- no `trial:`, no `repeat:` — single run, no folding.
- `repeat: N`, no `trial:` — strict pass^k over `N` attempts (unchanged).
- `trial: { n, threshold }` — pass-rate gating over `n` attempts, `trial` takes precedence
  over `repeat` when both are set.

`threshold` defaults to `1.0` inside `TrialPolicy` itself, i.e. strict pass^k with `n`
attempts instead of `repeat`'s `N` — the two knobs are equivalent at `threshold=1.0`.

## Adaptive/multi-turn default

Adaptive tests (`adaptive:` block, e.g. `agentaudit/packs/core/jailbreak/*.yaml`) are the
noisiest signal in the suite — turn generation and, optionally, an attacker/judge model both
add variance on top of the agent's own nondeterminism. `TestCase.effective_trial()`
(`core/schema.py`) defaults every adaptive test to `trial: { n: 3, threshold: 1.0 }` — more
samples, same strict bar — unless the test sets `no_default_trial: true` or supplies its own
`trial:` (which always wins). Non-adaptive tests get no default; the "unchanged unless you
opt in" rule holds for both categories.

## Gate math

`core/runner.py:_fold_attempts(attempts, threshold)` folds a list of per-attempt
`TestResult`s into one representative result:

- `threshold == 1.0` (strict, including plain `repeat:`): the first non-passing attempt's
  own status (`failed`/`error`) and evidence become the fold's status/evidence — unchanged
  from pre-trial behavior.
- `threshold < 1.0`: passes iff `passed / len(attempts) >= threshold`; on pass, the last
  attempt is the evidence representative (there is no single "the" failing attempt to point
  at). On fail, same first-non-passing rule as strict mode.

The fold always sets `TestResult.attempts` (one `Status` per attempt run — may be shorter
than the configured `n`, see early-stop below) and `TestResult.trial_threshold` (`None` for
every non-trial/strict result, the threshold value otherwise). Existing gate/score code
(`core/scoring.py`) reads `TestResult.status` and is untouched; `flaky` (pass^k attempts that
disagreed) is still `len(set(r.attempts)) > 1`, unaffected by trial threshold semantics.

## Sequential early-stop (cost control)

Running all `n` attempts even when the outcome is already obvious wastes agent calls. After
each attempt, `core/runner.py:_decided(passed, ran, n, threshold)` checks whether every
possible outcome of the *remaining* `n - ran` attempts still lands on the same side of
`threshold`:

```
best_rate  = (passed + remaining) / n   # every remaining attempt passes
worst_rate =  passed / n                # every remaining attempt fails
decided    = (best_rate >= threshold) == (worst_rate >= threshold)
```

This is an exact best/worst-case bound, not a probabilistic estimate — if `best_rate` and
`worst_rate` fall on the same side of `threshold`, no possible remainder changes the verdict,
so stopping there produces *exactly* the same result as running all `n`. There is no
confidence level to tune and no risk of a different verdict than the full run — early-stop
is safe to apply unconditionally, which is why it isn't a config knob.

Concretely: an always-passing agent under `trial(n=20, threshold=0.5)` stops at attempt 10
(`passed/n = 10/20 = 0.5` already clears the bar even if every remaining attempt fails) — a
50% cut. An always-failing agent under the same policy stops at attempt 11 (`best_rate =
(0+9)/20 = 0.45 < 0.5`, can never clear it). Both are covered by
`tests/test_runner.py::test_trial_policy_early_stop_cuts_cost_on_clear_cut_pass_case` and
`test_decided_stops_on_clear_all_pass_or_all_fail`.

## Cost model

Each attempt is exactly one extra agent call (the isolation-supervisor overhead documented
in `CLAUDE.md`'s validation-ladder section is paid once per `run()` call, not per attempt).
`TestResult.attempts`'s length **is** the call-cost evidence for that test — no separate
counter needed. Reports surface it:

- `agentaudit report --format md` — a "Trial policies" table (test id, n, pass rate,
  threshold, extra calls) plus a total extra-call-count line, only rendered when at least one
  result carries `attempts` (`reports/md.py:_trial_lines`).
- `agentaudit run` terminal table — the same n/pass-rate/threshold rows and total, printed
  only when the run used a trial/repeat policy (`cli.py:_print_table`).
- `agentaudit report --format json` — free: `attempts` and `trial_threshold` are plain
  `TestResult` fields, included in every JSON dump.

A token/dollar cost model is out of scope here — PRD-015 (proposed, not yet built) owns
general run cost/budget reporting. This PRD's reporting need is narrower (per-test trial
overhead) and is met by counting attempts, without introducing a cost abstraction.

## Non-goals / boundaries

- Tiered gating and flake quarantine (PRD-004) are a separate, still-unimplemented feature
  (`docs/specs/tiered-gating.md` is a design note only). `flaky` scoring in `core/scoring.py`
  is untouched by this change.
- No new store table, no Alembic migration — trial results round-trip through the existing
  `TestResult.model_dump_json()` path (`core/store.py:save_run`) with no schema change there.
