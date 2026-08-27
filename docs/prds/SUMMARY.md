# SUMMARY — Evaluation of AgentAudit & prioritized PRDs

Produced 2026-08-26 from a landscape survey, local behavioral verification, and
practitioner-pain-point research. Artifacts: [evaluation/landscape.md](evaluation/landscape.md) ·
[evaluation/assessment.md](evaluation/assessment.md) ·
[evaluation/pain-points.md](evaluation/pain-points.md) ·
[evaluation/readiness-checklist.md](evaluation/readiness-checklist.md).

**Verdict (short):** Partial yes — the sandbox side-effect model genuinely solves the hard
half of agent safety testing (judge-free, CI-gateable action evidence), but breadth,
statistically indefensible single-run gating, per-vertical onboarding cost, and a
first-run experience that used to report false failures keep it behind promptfoo/garak as a
default recommendation today.

## PRDs in priority order

| # | PRD | Group | One-liner |
|---|-----|-------|-----------|
| 1 | [PRD-006 — Core-pack sandbox skip](PRD-006-core-pack-sandbox-skip.md) | fixes | Stop reporting "sandbox has no bank" as three high-risk failures on every bare quickstart run; skip with a reason instead. **Implemented** (`fix/core-skip-without-sandbox`). |
| 2 | [PRD-008 — Statistical trial policies](PRD-008-statistical-trial-policies.md) | features | k≥3 trial runs with pass thresholds and early stopping so CI gates survive nondeterminism; RAMPART ships this natively today. |
| 3 | [PRD-007 — Docs output truthfulness](PRD-007-docs-sample-output-truthfulness.md) | fixes | README/quickstart samples showed categories and counts the tool cannot produce; corrected to reality. **Implemented** (`fix/readme-quickstart-output`). |
| 4 | [PRD-009 — Config-driven verticals](PRD-009-config-driven-verticals.md) | features | YAML sandbox toolkits + generic assertions so a third domain doesn't require writing Python; converts two demo islands into a platform. |
| 5 | [PRD-010 — Iterative attack loop](PRD-010-iterative-attack-loop.md) | improvements | Branching multi-turn campaigns (Crescendo/TAP-style) composed from existing evolve/archive/attacker primitives; closes the roadmap's own "Not built" stage. |
| 6 | [PRD-011 — Step-level timelines](PRD-011-step-level-timelines.md) | improvements | Turn-by-turn failure timelines with first-divergence markers in reports/dashboard, rendered from evidence already stored. |

Grouping: **features** = PRD-008, PRD-009 · **fixes** = PRD-006, PRD-007 ·
**improvements** = PRD-010, PRD-011.
Cross-references to pre-existing PRDs: PRD-004 (tiered gating/flake quarantine — complements
PRD-008's statistics), PRD-003 (production-failure loop — feeds evaluation debt),
PRD-005 (presentation readiness — see also evaluation/readiness-checklist.md).
