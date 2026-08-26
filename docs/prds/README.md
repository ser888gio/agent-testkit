# agentaudit — Product Requirements Documents

Prioritized PRDs derived from (a) a feature/quality audit of the repository and
(b) practitioner pain points gathered from forums, blogs, and research
(Reddit r/AI_Agents & r/LLMDevs, BuildPulse's flaky-eval series, OWASP Agentic
threat coverage, MCP tool-poisoning disclosures, arXiv work on adaptive prompt
injection evaluation). See each PRD's *Evidence* section for sources.

## Priority order

| # | PRD | Type | Why now |
|---|-----|------|---------|
| 1 | [PRD-001 — MCP Security Pack](PRD-001-mcp-security-pack.md) | Feature | Tool-description poisoning is the fastest-growing agentic attack class (2026); no mainstream open-source tester covers it against a live MCP server. Natural extension of the sandbox side-effect model. |
| 2 | [PRD-002 — DeepEval Adapter](PRD-002-deepeval-adapter.md) | Feature | Completes the external-integration triad (promptfoo ✅, garak ✅, DeepEval ❌) so teams using pytest-native evals feed one evidence store. Small, well-scoped, follows an existing adapter pattern. |
| 3 | [PRD-003 — Production-Failure → Regression Loop](PRD-003-production-failure-loop.md) | Feature | The most-requested workflow on practitioner forums: convert a production incident into a permanent regression case. Reuses the existing `evolve` review queue end to end. |
| 4 | [PRD-004 — Tiered Gating & Flake Quarantine](PRD-004-tiered-gating-flake-quarantine.md) | Improvement | Flaky LLM evals erode CI trust ("just rerun it" culture). Builds directly on existing pass^k folding; converts it from a scoring detail into a first-class gating policy. |
| 5 | [PRD-005 — Presentation Readiness](PRD-005-presentation-readiness.md) | Fix / Hygiene | Committed build artifacts, databases, and caches undermine credibility for demo/pitch scenarios. Cheap, unblocks everything public-facing. |

## Positioning context

agentaudit is an **assurance harness**, not another eval-scoring framework: its
differentiator is deterministic assertions over **sandbox side effects** rather
than reply text, plus CI-gateable exit codes and compliance-shaped evidence.
These PRDs deliberately deepen that axis instead of chasing metric breadth,
which is where DeepEval/promptfoo already compete.

## Companion document

- [Advisory improvement plan](ADVISORY-AUDIT.md) — read-only audit produced with
  the `improve` skill: bugs, security, DX, tech debt handoff plans.
