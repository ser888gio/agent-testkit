# PRD-015 — Claim the judge-free cost advantage (budget reporting + positioning)

**Type:** Improvement · **Status:** Proposed

## Problem
The reason eval suites die is not that teams disagree with them — it is that they cost too
much to run. The sharpest data point found: 500 cases with multi-judge grading takes
**~40 minutes and ~$20 per run, so engineers stop running it**, and **74% of teams running
agents in production have no automated regression test before a prompt change ships**
([Dev|Journal, synthesized from ~1,000 developer posts](https://earezki.com/ai-news/2026-04-21-what-1000-developer-posts-told-me-about-the-biggest-pain-points-right-now/)).

This reframes `pain-points.md` #8: cost is not a budgeting concern, it is **the mechanism by
which suites get abandoned** — and it collides head-on with PRD-008 (run k≥3 for statistical
validity), which multiplies an already-abandoned cost by k.

**AgentAudit has a structural advantage here that it never states.** Its assertions are
deterministic (19-entry registry, no LLM in the gating path — `core/judge.py` is a stop
condition, never a scorer). Per-test marginal cost is **one agent call, zero judge tokens**.
Every judge-based framework pays 2–5x that per test. The README's "How it compares" table
does not mention cost, determinism-of-gate, or run history — it competes only on axes where
AgentAudit is behind (probe breadth, maturity).

Two further unclaimed assets, both already shipped:
- **Run history / collaboration.** promptfoo's most-cited operational weakness is "no
  persistent dashboard, no shared experiment history, no way for a PM to stay in the loop"
  ([Braintrust](https://www.braintrust.dev/articles/best-promptfoo-alternatives-2026)).
  AgentAudit ships org-scoped SQLite persistence, per-test history across runs, and a job
  queue. No row for this exists in the comparison table.
- **Architectural convergence.** Recent work argues tool calls should be gated by
  deterministic policy *before* execution rather than judged after
  ([arXiv 2603.20953](https://arxiv.org/pdf/2603.20953)); practitioners independently
  describe "grade side effects by checking mock SMTP logs rather than asking the LLM if it
  sent an email." That is AgentAudit's architecture, described by others as the target state.

Against this: there is **no budget or duration reporting**, and the isolation supervisor
costs ~2.5s process spawn per run — documented in `CLAUDE.md` as a test-suite cost, but paid
per production run too.

## Proposed solution
Two halves, both small.

**Measure (makes the claim checkable):**
- Record per-run agent-call count, total wall-clock, and per-test latency (latency is
  already captured); surface as a `cost` block in the JSON report and a footer line in the
  terminal table and Markdown report.
- Optional `--budget-calls N` / `--budget-seconds N` that stops a run and reports partial
  results rather than blowing a CI budget — pairs directly with PRD-008's sequential stop.
- Report the isolation-supervisor overhead separately from agent time, so users can see
  what is harness cost vs agent cost.

**Position (claims what already exists):**
- Add rows to the README comparison table: **gate determinism** (no judge tokens in the
  gating path), **cost per test**, **run history/collaboration**.
- One sentence above the fold: gates on deterministic side-effect assertions — no LLM-judge
  variance, no judge tokens.
- Cite the convergence (arXiv 2603.20953 + practitioner posts) in `docs/architecture.md` as
  external validation of the design.

## Success criteria
- Every run reports agent-call count and wall-clock; a documented worked example compares
  agentaudit's per-test cost against a judge-based run of the same tests.
- `--budget-*` halts cleanly with partial results and a non-confusing exit code.
- README comparison table has rows for determinism, cost, and history; the judge-free line
  is above the fold.
- Harness overhead is visible and separated from agent time.

## Priority & effort
**P1** — does not fix a defect, but it is the cheapest available win on the metric that
decides whether suites survive contact with CI, and it makes PRD-008's cost story
defensible. · **Effort: S** (measurement + docs); **M** if budget-based early stopping is
built with PRD-008.

## Open questions
- Token counts need the target to report usage; is call-count + wall-clock enough for a
  black-box tool that deliberately doesn't see inside the agent?
- Does `--budget-*` exit 0 (budget is not a safety failure) or a distinct code?
- Is the ~2.5s/run isolation overhead worth reducing (process reuse across tests), or just
  worth disclosing?
