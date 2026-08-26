# PRD-004: Tiered Gating & Flake Quarantine

**Type:** Improvement · **Priority:** 4

## Problem

LLM eval flakiness is the #1 trust-killer reported by engineering teams: gates
that "open and close on their own" train people to rerun until green, which
destroys the CI signal and (in regulated shops) constitutes bypassing a
documented control. agentaudit is better positioned than most because its
verdicts are deterministic assertions, but two residual nondeterminism sources
remain: genuinely borderline agents (pass^k spread) and optional LLM-driven
features (judge stop conditions, attacker refinement). Today pass^k folding
exists (`_fold_attempts` at `core/runner.py:318`, surfaced as `flaky` in
`core/scoring.py`) but there is no *policy* around it: no quarantine, no
tiering, no history-based flake scoring visible to users.

## Evidence

- BuildPulse's flaky-eval series (Jul–Aug 2026): tiered suites (hard-gating
  contract tier vs reporting-only sweep), per-test flake scores, and explicit
  quarantine with audit trail are the recommended practice; rerun-until-green
  is called out as an audit finding in SOC 2 contexts.
- r/AI_Agents / r/LLMDevs threads repeatedly describe eval CI as "an expensive
  random number generator."
- agentaudit README already documents pass^k but leaves policy to the caller.

## Goals

1. **Two gate tiers** declared per run config:
   - `blocking`: deterministic safety/critical tests — any failure fails the gate.
   - `reporting`: probabilistic/borderline tests — failures inform score and
     reports but never flip the exit code.
2. **Quarantine workflow**: a persistently-flaky test can be quarantined
   (moves to reporting tier automatically) with reason, owner, and expiry;
   quarantines surface prominently in reports and the dashboard — visible, not
   silent.
3. **Flake history**: per-test flake rate computed from stored runs
   (`core/store.py` already persists per-test results and offers
   `score_trend`); shown on the test detail page and included in JSON/JUnit
   exports so external flake trackers can consume it.

## Non-goals

- Statistical auto-tuning of thresholds.
- Making the judge a scorer (explicitly rejected design, `core/judge.py:1-25`).
- Cross-instance flake aggregation (single-store scope).

## User stories

- As a platform engineer, I mark my latency-budget and robustness categories as
  `reporting` in run config, so a slow-but-safe build never blocks merges while
  safety regressions still do.
- As a developer bitten by one unstable jailbreak-ladder case, I quarantine it
  for 30 days with a reason; the HTML report shows "quarantined (expires
  2026-09-30)" instead of a red X I'm tempted to rerun away.
- As an auditor, I export a record of every quarantine decision (who, when,
  why, expiry) alongside the compliance report.

## Requirements

1. Tier declaration in run/target YAML validated by `core/config.py`;
   default remains today's behavior (everything blocking) — opt-in change.
2. Gate computation moves into `core/scoring.py::score` with an explicit tiered
   mode; empty-run fail-closed semantics preserved unchanged.
3. Quarantine persisted via new store table + Alembic migration
   (`infra/alembic/versions/`); expiry enforced at plan/load time, never
   retiring a still-failing *critical* test (mirror `evolve`'s rule).
4. Flake rate = fraction of historical runs where the folded result was
   `flaky`; window configurable, computed read-only from existing rows.
5. Reports: tier + quarantine annotations in `reports/{json,junit,md,html}.py`.
6. Tests: `tests/test_scoring.py` (tiered gating incl. fail-closed),
   `tests/test_store.py` (quarantine CRUD/expiry), `tests/test_web.py`
   (dashboard endpoints authz).

## Success metrics

- Teams using tiers report zero false-blocking merges over 30 days (telemetry
  optional/local: measurable via run history instead).
- Quarantined tests have documented expiry in 100% of cases (enforced).
- No increase in full-suite runtime; flake-rate queries stay < 100 ms on 10k
  result rows.

## Open questions

- Should `flaky` folded outcomes in the blocking tier warn-only or hard-fail
  when attempts are exhausted?
- Dashboard UX for quarantine creation — reuse the generated-test review UI
  patterns?
