# PRD-010 — Iterative attack loop (branching multi-turn campaigns)

**Type:** Improvement · **Status:** Proposed

## Problem
The roadmap's own centerpiece — "attack iteratively" — is the one stage marked "Not built"
(`website/docs/limits.md`), while fixed-ladder adaptive tests are shipped. Meanwhile every
major alternative now does iterative/adaptive attacks: promptfoo strategies include
Crescendo and GOAT ([0xClaw survey](https://www.0xclaw.dev/blog/best-tools-for-testing-prompt-injection-in-ai-agents)),
DeepTeam ships 20+ attacks including tree jailbreaking and recursive hijacking
([repo](https://github.com/confident-ai/deepteam)), garak v0.15 added multi-turn GOAT plus
an agent-breaker probe
([dreaming.press](https://dreaming.press/posts/garak-vs-pyrit-vs-promptfoo.html)). The README's
"narrower than garak" concession understates a widening gap (Task 1 finding #3). AgentAudit
has the right primitives already: `Archive` (elite-attack-per-cell coverage),
`evolve` (generate→validate→admit with human review), attacker/judge seams.

## Proposed solution
Compose those primitives into a branching campaign runner: goal + archive seeding →
LLM-driven turns that branch on agent replies (Crescendo/TAP-style escalation, reusing
`build_refining_strategy`'s seam) → stop conditions via existing judge → survivors admitted
through the existing review queue so audited evidence stays human-gated. Budget-bounded
(max turns/tokens per campaign) per pain-points.md #8.

## Success criteria
- Campaign mode finds at least one payment/exfil bypass on the overtrusting demo agents that
  the fixed ladders miss (measurable on the bundled fixtures).
- Runs fully offline-degradable (falls back to ladders when no attacker model configured).
- Every admitted campaign result carries provenance (`techniques`, `degraded`) as today.

## Priority & effort
P1 — closes the roadmap's most-advertised hole before evaluators notice it · Effort: L

## Open questions
- Branching factor vs cost budget; does `Archive` cell coverage translate to campaign pruning?
- Judge fallback semantics for branching decisions (stop-condition-only rule must hold).
