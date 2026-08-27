# PRD-011 — Step-level failure timelines in reports and dashboard

**Type:** Improvement · **Status:** Proposed

## Problem
AgentAudit captures step-level truth (per-turn requests, sandbox event stream, diff) but
reports collapse it into pass/fail plus final evidence — so a failed test answers "what"
but not "which turn/tool call went wrong". The field has moved to step-level evaluation:
outcome evals "hand back one number that cannot tell them apart" — failing at step 2 of 7 vs
step 7 of 7 are different bugs ([dev.to step-level survey](https://dev.to/james_oconnor_dev/step-level-agent-evals-exist-now-most-teams-still-grade-the-finish-line-1bb5));
trajectory scoring is table stakes in DeepEval/promptfoo/Langfuse/LangSmith (same source);
practitioners score trajectories because "final output alone misses most of the failures"
([Reddit r/AI_Agents mirror](https://reddit.sentinel-team.org/posts/1uh4b4l/snapshots/2026-07-03T10%3A54%3A57.799536Z)).
Task 2 §2 also flagged "act on findings" as the weakest user-path step.

## Proposed solution
Render each multi-turn test result as a timeline: turn-by-turn input/response summaries,
sandbox events interleaved by turn, first-divergence marker (the turn where the first failing
assertion's precondition appeared). Expose in Markdown/HTML reports, JUnit attachments, and
the dashboard RunDetail. Deterministic rendering from data already stored — no new capture
path, redaction rules inherited.

## Success criteria
- For the overtrusting-agent demo run, a reader can identify the poisoning turn in <30s from
  the report alone.
- No evidence appears in timelines that isn't already redacted under the same policy
  (security-P0 suite stays green).
- HTML + md + dashboard parity; JSON gains an optional `timeline` block consumed by all three.

## Priority & effort
P1/P2 — high diagnosis-value, low risk, builds purely on stored evidence · Effort: M

## Open questions
- Long transcripts: full timeline or first-divergence window by default?
- Does JUnit's format support the attachment natively or does it need a companion file?
