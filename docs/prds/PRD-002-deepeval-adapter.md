# PRD-002: DeepEval External Adapter

**Type:** Feature · **Priority:** 2

## Problem

Teams doing agent quality/security work almost always run more than one
framework. agentaudit already normalizes **promptfoo** and **garak** output
into its own `TestResult` schema (`PromptfooAdapter` at
`backend/agentaudit/core/adapters.py:359`, `GarakAdapter` at `:519`), so their
findings land in the same store, dashboard, and CI gate. **DeepEval** is the
notable absence — it is the leading pytest-native framework (50+ metrics,
G-Eval, agent tracing) and the natural companion for engineers who write their
own behavioral tests in Python. Today those users must keep two separate
reporting worlds.

## Evidence

- Framework comparisons through 2026 consistently pair DeepEval (pytest-native
  metrics) with promptfoo (CLI red-teaming); teams report using both together.
- agentaudit's own docs position external integrations as "Wave 1" work
  (`docs/IMPLEMENTATION-TESTS-PLAN.md`); promptfoo + garak shipped, DeepEval
  did not.
- Forum pattern: "I use DeepEval for ML pipeline evals and promptfoo for
  security tests" — the missing piece is a unified evidence/gate layer, which
  is precisely agentaudit's role.

## Goals

1. `DeepEvalAdapter(ExternalEvalAdapter)` that executes a user-selected set of
   DeepEval test files (or a whole suite) in a subprocess, parses the resulting
   JSON/JUnit output, and normalizes each test case into agentaudit
   `TestResult`s (id, category, status, latency, evidence pointer).
2. CLI parity with existing adapters: `agentaudit run ... --external deepeval`
   (`cli.py:368` pattern) and catalog selection via `core/catalog.py`.
3. Findings appear in the dashboard runs view and are comparable via
   `agentaudit compare` like any native run.

## Non-goals

- Re-implementing any DeepEval metric inside agentaudit.
- Bidirectional sync (exporting agentaudit packs as DeepEval tests) — possible
  follow-up.
- Supporting Confident AI cloud features.

## User stories

- As an engineer with an existing DeepEval suite, I run
  `agentaudit run <pack> --external deepeval --external-path tests/evals/`
  and my DeepEval outcomes show up in the same run, score, and HTML report as
  agentaudit's own probes.
- As a team lead, I gate CI on one exit code that reflects both frameworks'
  verdicts, instead of stitching two CI steps.
- As a security reviewer, I can diff today's DeepEval results against last
  week's using the regression gate (`core/regressions.py`).

## Requirements

1. Subprocess execution mirrors `ExternalEvalAdapter` lifecycle in
   `core/adapters.py:186`; honor timeouts and never let adapter failures crash
   the host run (runner contract, `core/runner.py:341`).
2. Parse `deepeval test run ... --json-output` artifacts; map metric scores to
   pass/fail using DeepEval's own thresholds — never re-judge locally.
3. Category mapping table (DeepEval metric → agentaudit category) kept in one
   declarative dict next to the adapter, unit-tested exhaustively.
4. Redaction invariant preserved: any error text pulled from the subprocess is
   passed through `core/redaction.py` before storage (enforced in
   `tests/test_security_p0.py` style).
5. Tests: `tests/test_adapters_deepeval.py` with recorded fixture outputs
   (no live LLM dependency), including malformed-output failure paths.

## Success metrics

- Round-trip of a representative DeepEval JSON fixture yields correct statuses
  for all documented metric types in fixtures.
- Docs example works copy-paste: install deepeval → run adapter → see merged
  report.
- Zero flake across the adapter test file in CI (it must be fully offline).

## Open questions

- Minimum supported DeepEval version (pin to JSON schema stability, likely ≥ 2.x).
- Should adapter runs be eligible for the compliance report, or marked
  out-of-scope for control mapping?
