# PRD-016 — Close the loop: promote a production incident into a test case

**Type:** Feature · **Status:** Proposed · **Extends:** PRD-003 (which shipped the parser)

## Problem
"Without feedback loops connecting evaluation results back into the pipeline, agents degrade
silently until a user escalation forces a postmortem"
([MLflow, 2026](https://mlflow.org/articles/building-production-ready-ai-agents-in-2026/)).
Agents pass their suites, then hallucinate tool calls, retry failed requests in infinite
loops, and cost 50x budget in production
([Dev|Journal](https://earezki.com/ai-news/2026-04-21-what-1000-developer-posts-told-me-about-the-biggest-pain-points-right-now/)).

This is distinct from `pain-points.md` #5 (evaluation debt = "the suite ages"). Here,
**production already told you the answer and nothing consumed it.** The failure you shipped
is not in the suite, so it can ship again.

PRD-003 shipped `core/incidents.py` (120 lines): incident transcript parsing with a
redaction boundary. That is the right primitive and the hard part is done. But **there is no
path from a parsed incident to a runnable test**, and no CLI verb — so the loop is still
open.

The pieces to connect it already exist:
- `core/incidents.py` — parse + redact a transcript
- `core/evolve.py` (467 lines) — candidate generation → novelty/effectiveness filter →
  **human review queue** → promotion into the baseline
- the dashboard already renders a review queue for generated tests

## Proposed solution
Add `agentaudit incident import <transcript> [--target …]` that turns a real failure into a
proposed test case and parks it in the **existing** evolve review queue — reusing the
promotion path rather than building a second one.

Pipeline: parse + redact (PRD-003) → derive a candidate `TestCase` (turns from the
transcript; category/risk inferred or prompted) → **propose assertions** from the observed
failure, preferring side-effect assertions where the target has a sandbox
(`no_payment_created`, `tool_not_called`, `no_repeated_tool`) → verify the candidate
*reproduces* the failure against the current agent → queue for human review → promote.

The reproduce-check is what makes this trustworthy: a candidate that does not reproduce is
flagged rather than promoted, so the suite never fills with tests that assert nothing.

Note `no_repeated_tool` already exists and directly expresses the infinite-retry failure
mode named in the source above — that assertion is shipped and unmarketed.

**Non-goal:** live production monitoring. AgentAudit is a black-box test harness; this
imports an incident someone hands it. Ingesting live traffic is a different product.

## Success criteria
- A redacted incident transcript becomes a queued candidate test in one command.
- Candidates are marked reproduces / does-not-reproduce against the current agent.
- Nothing enters the audited baseline without human promotion (preserves the existing
  `evolve` guarantee — no model- or incident-derived test counts as evidence unreviewed).
- Redaction runs before persistence, and a test proves it (`core/incidents.py` boundary
  already establishes this; extend to the new path).
- A worked example in `docs/` walks an incident → queued test → promoted test → regression
  caught by `compare`.

## Priority & effort
**P1** — high user value and the strongest retention story (the suite gets better every time
production breaks), but it presupposes teams already run agentaudit; P0 items win the
first-run and the wedge first. · **Effort: M** (assertion inference is the hard part;
parser, queue, and promotion all exist)

## Open questions
- What transcript formats? (OTel spans, LangSmith/Langfuse exports, plain JSON?) Starting
  with one documented shape is probably right.
- Can assertions be inferred usefully without a sandbox, or is this a sandbox-only feature
  in practice?
- Should a non-reproducing candidate still be queued (flaky/nondeterministic failure — see
  PRD-008 trials) or rejected?
- Does an imported incident carry provenance into the compliance report as evidence of a
  real-world failure being covered?
