# Task 4 addendum — skill availability correction + revised blockers (2026-08-27)

Extends [`readiness-checklist.md`](readiness-checklist.md). Its ten checklist items stand.
Two corrections and two additions.

## Correction 1 — presentation skills *are* available

The original checklist stated "no pitch-deck, demo-scripting, or README-polish skill is
installed in this environment." True of *installed* skills, but the ecosystem has several
installable ones (`npx skills find`):

| Skill | Installs | Note |
|---|---|---|
| `owl-listener/designer-skills@presentation-deck` | ~2.0k | Only one clearing the ≥1k quality bar the `find-skills` guidance sets |
| `mblode/agent-skills@presentation-creator` | ~544 | Below bar |
| `aaronvanston/skills-presentations@presentation-pitch-deck` | ~288 | Below bar |
| `shawnpang/startup-founder-skills@pitch-deck` | ~236 | Below bar |

Nothing was installed — that is the maintainer's call. Also relevant and already installed:
`ogilvy` (persuasive copy → README headline, PRD-015's positioning lines) and `impeccable`
(UI polish → dashboard demo surface).

## Correction 2 — blocker #1 is still open, and its fix was misdiagnosed

The checklist listed "truthful first run" as a blocker, fixed on
`fix/core-skip-without-sandbox`. **That branch was never merged** — verified on `develop`,
the bare `run core` against a harmless stub agent still reports three high-risk failures
reading `sandbox has no bank`. It is also a pack-taxonomy defect rather than a missing skip
(see [PRD-012](../PRD-012-core-pack-taxonomy.md)).

**A live demo today would show three fabricated security failures against a harmless agent.**
Still the #1 blocker.

## Addition — new blocker: the Markdown report crashed

`agentaudit report --format md` exited 1 with `UnicodeEncodeError` on Windows whenever the
run had failures — i.e. exactly the run you would demo. Fixed on
`fix/md-report-windows-encoding` ([PRD-014](../PRD-014-console-encoding-and-windows-ci.md));
**verify it is merged before demoing**, and prefer `--out FILE` on stage as belt-and-braces.

## Addition — sharpen the pitch with what is already shipped

Per [`landscape-addendum.md`](landscape-addendum.md) and
[`pain-points-addendum.md`](pain-points-addendum.md), three true claims are missing from the
current pitch:

1. **"Every MCP scanner is static. We test whether your agent actually falls for it."** —
   the one claim with no competitor. Needs PRD-013 to be more than one test deep.
2. **"No judge in the gating path — no judge tokens, no judge variance."** — a structural
   cost and trust advantage over every judge-based framework, never stated.
3. **"Run history and per-test trends across runs"** — promptfoo's most-cited operational
   gap, already shipped here.

## Revised blocker order

1. **PRD-012** — quickstart must stop inventing failures *(open)*
2. **PRD-014** — Markdown report must not crash *(fixed, merge pending)*
3. Docs match reality — re-verify after both merge
4. The 90-second money shot (safe agent green → overtrusting agent 7 criticals, `Gate: BLOCK`,
   exit 1, one sandbox diff) — verified working
5. Add the three claims above, above the fold
6. Then the original checklist items 5–10 (compliance in demo path, screenshots, hosted
   try-it, repo hygiene, limits page, comparison-table refresh — now including RAMPART,
   ProofAgent, and the MCP scanners)
