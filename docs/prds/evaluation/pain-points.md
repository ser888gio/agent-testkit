# Task 3 — What engineers actually struggle with (ranked pain points)

Method: practitioner posts and threads (Reddit via mirror, Hacker News, dev communities),
plus repo issues where discoverable, plus recent engineering blog write-ups grounded in
field-testing agents. Ranked by recurrence and intensity. Each entry notes AgentAudit's
coverage.

## 1. Nondeterminism makes single-run CI gates meaningless
A "flaky" agent test is usually a sample of size one read as a verdict; the 95% CI on a
pass rate shrinks from ~14% at one run to ~3% at three — gate on k≥3 / lower bound, not one
draw ([dreaming.press](https://dreaming.press/posts/how-to-test-a-non-deterministic-ai-agent.html)).
Same conclusion from a distributed-systems framing: pass@k vs pass^k, percentile metrics,
seeded fault injection
([saumilsrivastava.ai](https://www.saumilsrivastava.ai/blog/agent-evaluation-is-a-distributed-systems-problem)).
RAMPART ships `@pytest.mark.trial(n=10, threshold=0.8)` for exactly this
([docs](https://microsoft.github.io/RAMPART/usage/ci-integration/)).

**AgentAudit: ignores.** `repeat` + pass^k folding exist in the runner but default to 1;
no threshold policy, no guidance. (Repo PRD-004 targets this; unimplemented.)

## 2. LLM-as-judge is distrusted as a primary signal
"The judge is inconsistent… biased toward longer answers… calibrating it feels like stacking
prompt rules on top of prompt rules" — multi-agent eval engineer
([Reddit r/AI_Agents thread mirror](https://reddit.sentinel-team.org/posts/1uh4b4l/snapshots/2026-07-03T10%3A54%3A57.799536Z));
"LLM as critic… I've never seen empirical evidence that this works"
([HN 44715163](https://news.ycombinator.com/item?id=44715163)); judged metrics carry known
position/length/agreeableness biases and high error rates on complex tasks
([dev.to evaluation-debt](https://dev.to/paultwist/the-evaluation-debt-you-dont-know-you-have-why-agent-evals-fail-in-production-2md8)).
Practitioners land on: judge = triage/smoke; deterministic checks + thin human audits = signal.

**AgentAudit: addresses** — deterministic assertion registry, judge explicitly a stop
condition never a scorer (`core/judge.py` spec). This is a genuine marketing asset that the
README undersells.

## 3. Final-answer grading misses tool-level failures; environment state is the real evidence
"An agent can produce a decent final answer while doing a lot of things badly on the way
there" ([pragmatic-engineer](https://pragmatic-engineer.hashnode.dev/why-agent-evaluation-is-harder-than-model-evaluation));
"the agent's self-report is hearsay. The environment is evidence" — graders query MailHog/SQLite,
not replies ([saumilsrivastava.ai](https://www.saumilsrivastava.ai/blog/agent-evaluation-is-a-distributed-systems-problem));
step-level eval split: deterministic invariants (no unauthorized tools, no arg corruption)
gate cleanly; judgment questions need judges
([dev.to step-level survey](https://dev.to/james_oconnor_dev/step-level-agent-evals-exist-now-most-teams-still-grade-the-finish-line-1bb5)).

**AgentAudit: partially addresses.** Sandbox diffs/events are exactly "environment as
evidence" — its best differentiator. But reports expose pass/fail + final diff, not a
step-level timeline of *which turn/tool call* went wrong; diagnosing a failure still means
reading raw request/response evidence.

## 4. Integration realism: "runnable ≠ evaluable"
Field-testing 19 real agents across 150+ candidates: adapter realism, blank completions,
dependency quarantines — "the bottleneck was adapter realism, not judge sophistication"
([pragmatic-engineer follow-up](https://pragmatic-engineer.hashnode.dev/why-agent-validation-needs-release-discipline-not-better-demos)).
Teams underestimate the wiring cost of getting a real agent under test at all.

**AgentAudit: partially addresses.** Black-box HTTP targeting avoids instrumentation
(real advantage), but anything outside the two verticals requires hand-writing a `Sandbox`
subclass before side-effect tests mean anything.

## 5. Evaluation debt: suites rot as traffic drifts
"38% of AI teams say it's their primary blocker"; super-majority must constantly update
tests as new failures appear; offline sets measure the past
([dev.to evaluation-debt](https://dev.to/paultwist/the-evaluation-debt-you-dont-know-you-have-why-agent-evals-fail-in-production-2md8)).

**AgentAudit: partially addresses.** `evolve` → review queue → promotion is the right
architecture for refreshing packs, but it's off unless external attacker-model env vars are
set, and there's no production-failure import path yet (repo PRD-003).

## 6. Flakiness handling culture: quarantine vs statistics
Teams either rerun-until-green or quarantine flakes, both destroying signal; statistical
trials with explicit thresholds are the emerging alternative
([dreaming.press](https://dreaming.press/posts/how-to-test-a-non-deterministic-ai-agent.html),
[RAMPART docs](https://microsoft.github.io/RAMPART/usage/ci-integration/)).

**AgentAudit: ignores** today (counts `flaky` in scoring output but gates on single runs).
Overlaps #1; listed separately because the *workflow* (quarantine policy) is distinct from
the *statistic*.

## 7. Compliance evidence is scarce in OSS testing tools
Compliance mapping (OWASP/NIST/MITRE/EU AI Act) called "rare in open-source tooling" and a
main driver of promptfoo's dominance
([BeyondScale](https://beyondscale.tech/blog/ai-red-teaming-tools-comparison-2026),
[appsecsanta](https://appsecsanta.com/ai-security-tools/garak-vs-promptfoo)); garak leaves
mapping to the analyst.

**AgentAudit: addresses** — built-in EU AI Act / ISO 42001 / NIST report with covered/gaps/
not-tested sections. Underleveraged: nothing in the quickstart surfaces it.

## 8. Cost anxiety about repeated/adversarial runs
Running every case k times multiplies invoice size; sequential testing recovers most of it
(78–100% cost reduction claims)
([dreaming.press](https://dreaming.press/posts/how-to-test-a-non-deterministic-ai-agent.html));
garak sweeps multiply inference calls
([aicoolies](https://aicoolies.com/comparisons/promptfoo-vs-garak)).

**AgentAudit: partially addresses.** Planner cost-ranks selections and `--max-tests` caps
runs; no budget reporting or sequential stopping.
