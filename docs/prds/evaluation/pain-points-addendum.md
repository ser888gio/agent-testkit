# Task 3 addendum — pain points missed by the first pass (2026-08-27)

Extends [`pain-points.md`](pain-points.md), whose eight ranked pain points hold up. These
are additional recurring complaints that survey did not surface, ranked by how directly
they bear on AgentAudit's roadmap. Nothing here restates it.

## A. Eval suites are too slow and too expensive to actually run — so teams stop running them

The sharpest formulation found: running 500 cases through a frontier model with multi-judge
grading takes **~40 minutes and ~$20 per run, so engineers stop running it**; and **74% of
teams running agents in production have no automated regression test that runs before a
prompt change ships**
([Dev|Journal, from ~1,000 developer posts](https://earezki.com/ai-news/2026-04-21-what-1000-developer-posts-told-me-about-the-biggest-pain-points-right-now/)).

This reframes `pain-points.md` #8 (cost anxiety). Cost is not a budgeting concern — it is
the mechanism by which suites get abandoned. The binding constraint is **wall-clock and
dollars per CI run**, and it interacts badly with #1 (run k≥3 for statistical validity):
naive trials multiply an already-abandoned cost by k.

**AgentAudit: partially addresses, and is unusually well-positioned.** Its assertions are
deterministic and judge-free, so per-test marginal cost is one agent call — no judge tokens.
That is a structural cost advantage over every judge-based framework and it is **never
stated anywhere in the README**. Against it: no budget/duration reporting, no sequential
stopping, and the isolation supervisor adds ~2.5s process spawn per run (documented in
`CLAUDE.md` as a *test-suite* cost, but it is paid per production run too).

## B. Silent degradation: no loop from production failures back into the suite

"Without feedback loops connecting evaluation results back into the pipeline, agents degrade
silently until a user escalation forces a postmortem"; the gaps between tool calls,
retrieval, and the audit trail are where real deployments break
([MLflow, Building Production-Ready AI Agents 2026](https://mlflow.org/articles/building-production-ready-ai-agents-in-2026/)).
Related: agents pass test suites, then hallucinate tool calls, retry failed API requests in
infinite loops, and cost 50x budget in production
([Dev|Journal](https://earezki.com/ai-news/2026-04-21-what-1000-developer-posts-told-me-about-the-biggest-pain-points-right-now/)).

Overlaps `pain-points.md` #5 (evaluation debt) but is distinct: #5 is "the suite ages", this
is "**production already told you the answer and nothing consumed it**."

**AgentAudit: partially addresses.** `core/incidents.py` (PRD-003, merged) parses incident
transcripts with a redaction boundary — the right primitive. But there is no path from a
parsed incident to a promoted test case, and no CLI verb for it.

Note the infinite-retry failure mode is *already* expressible: `no_repeated_tool` exists in
the assertion registry and the MCP scenario uses it. Loop detection is shipped and unmarketed.

## C. The supply-chain layer is now the dominant agent-security concern, and it is behavioral

"AI agent security in 2026 is a supply chain problem first, a prompt injection problem
second" ([cyberdesserts](https://blog.cyberdesserts.com/ai-agent-security-risks/)). Snyk's
ToxicSkills study: prompt injection in **36%** of agent skills scanned, 1,467 vulnerable,
**534 with critical issues**, plus an active malware campaign distributing 30+ malicious
skills via ClawHub — "no code signing, no security review, no sandbox by default"
([Snyk](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/),
[Orca](https://orca.security/resources/blog/ai-agent-skill-supply-chain-security/),
[CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-skill-md-agent-context-poisoning-20260506/)).

Every tool in that space is a **static scanner** (see `landscape-addendum.md`). None answers
the question a team actually needs answered before shipping: *given a poisoned tool
description reaches my agent, does my agent comply?*

**AgentAudit: barely addresses — one test.** This is the highest-leverage gap found in this
whole review: maximum market urgency, zero behavioral competition, and the sandbox
primitive already built (`domains/mcp/sandbox.py`).

## D. Deterministic pre-action authorization is emerging as the expected control

Recent work argues tool calls should be gated by deterministic policy *before* execution
rather than judged after
([arXiv 2603.20953, "Before the Tool Call"](https://arxiv.org/pdf/2603.20953)), and the
harness pattern practitioners describe is "grade side effects by checking mock SMTP server
logs rather than asking the LLM if it sent an email"
([dev.to survey](https://dev.to/thedailyagent/5-open-source-tools-for-testing-ai-agents-before-they-break-production-5d9c)).

**AgentAudit: addresses — this is literally its architecture.** The academic and
practitioner consensus is converging on the design AgentAudit already implements. It is a
positioning asset (cite the convergence), not a gap.

## Ranking these against the original eight

Merged priority for the pain points that bear on roadmap decisions:

1. `pain-points.md` #1 + #6 — statistical trials (already PRD-008)
2. **C (supply-chain / MCP behavioral testing)** — new; largest uncontested opportunity
3. **A (cost/wall-clock as abandonment driver)** — new framing; AgentAudit has an unclaimed structural win
4. `pain-points.md` #3 — step-level timelines (already PRD-011)
5. `pain-points.md` #4 — onboarding a vertical (already PRD-009)
6. **B (production→suite feedback loop)** — extends PRD-003, which stopped at parsing
