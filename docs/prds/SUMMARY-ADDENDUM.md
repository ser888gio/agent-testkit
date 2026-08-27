# SUMMARY ADDENDUM — gap review (2026-08-27)

A second pass over [`SUMMARY.md`](SUMMARY.md) (2026-08-26), scoped to **what that review
missed**. Repo state (not the original task brief) was treated as authoritative, and every
behavioral claim was verified by running the tool on `develop`.

New artifacts: [evaluation/landscape-addendum.md](evaluation/landscape-addendum.md) ·
[evaluation/assessment-addendum.md](evaluation/assessment-addendum.md) ·
[evaluation/pain-points-addendum.md](evaluation/pain-points-addendum.md) ·
[evaluation/readiness-checklist-addendum.md](evaluation/readiness-checklist-addendum.md)

## What the first pass missed

1. **Two product categories absent from the landscape.** MCP/skill supply-chain scanners
   (Snyk `agent-scan` ~3.0k★, Invariant `mcp-scan`, eSentire `mcp-scanner`, MCP-Shield) and
   one direct positional competitor (ProofAgent Harness — adversarial multi-turn + CI +
   compliance across **25** frameworks, local-first, 27★).
2. **A live P0 crash.** `report --format md` exited 1 with `UnicodeEncodeError` on Windows —
   *only when a run had failures*, in the format CI pipes to stdout. **Fixed** on
   `fix/md-report-windows-encoding`.
3. **The quickstart still lies on `develop`.** PRD-006's branch was never merged, and the
   diagnosis was wrong anyway: it is a **pack-taxonomy** defect (three treasury tests filed
   under `packs/core`), not a missing skip.
4. **Cost is the abandonment mechanism, not a budgeting concern** — and AgentAudit's
   judge-free gate is a structural cost advantage it never claims.
5. **The MCP wedge is one test deep** in the only category with no behavioral competitor.

## Verdict delta

Same verdict as the first pass — **partial yes** — with two adjustments:

- **More positive on the wedge.** It is narrower and more specific than "sandbox side
  effects": it is *behavioral* MCP/tool-poisoning testing. Four static scanners and one
  positional twin all stop at metadata or conversation text.
- **More negative on first contact.** Two of the first three commands a new user runs were
  defective on `develop`. Both are small fixes; both destroy trust while it is being formed.
  This outranks probe breadth — breadth is a disclosed, gradual gap; a lying quickstart is an
  undisclosed correctness bug in the first 60 seconds.
- **Compliance is a weaker differentiator than claimed** (ProofAgent: 25 frameworks;
  promptfoo ships OWASP/NIST/MITRE/EU AI Act presets).

## New PRDs in priority order

| # | PRD | Group | Priority · Effort | One-liner |
|---|-----|-------|---|---|
| 1 | [PRD-012 — Core-pack taxonomy](PRD-012-core-pack-taxonomy.md) | fixes | P0 · S | Three treasury tests live in `packs/core` and can only fail on the documented quickstart; re-assert them instead of skipping (supersedes PRD-006's approach). |
| 2 | [PRD-013 — MCP behavioral pack](PRD-013-mcp-behavioral-pack.md) | features | P0 · L | Grow the one-test MCP pack to 12–15 scenarios; every competitor is a static scanner, so the behavioral question is unserved. |
| 3 | [PRD-014 — Console encoding + Windows CI](PRD-014-console-encoding-and-windows-ci.md) | fixes | P0 (fixed) · P1 CI · S | `report --format md` crashed on failing runs on Windows. Fixed; needs a Windows CI lane so the class cannot return. |
| 4 | [PRD-015 — Cost + positioning](PRD-015-cost-and-positioning.md) | improvements | P1 · S–M | Report call-count/wall-clock and claim the judge-free cost, determinism, and run-history advantages the README omits. |
| 5 | [PRD-016 — Incident → test promotion](PRD-016-incident-to-test-promotion.md) | features | P1 · M | Connect PRD-003's incident parser to `evolve`'s review queue so production failures become tests. |

Grouping: **features** = PRD-013, PRD-016 · **fixes** = PRD-012, PRD-014 ·
**improvements** = PRD-015.

## How these interact with the existing PRDs

- **PRD-012 supersedes the approach in PRD-006** (re-home/re-assert, don't skip). Keep a
  narrow skip as defense-in-depth for user-written packs.
- **PRD-015 is a prerequisite for PRD-008 being credible**: k≥3 trials multiply cost, so
  cost must be measurable before trials are defensible.
- **PRD-016 completes PRD-003**, which stopped at parsing.
- **PRD-013 is where PRD-009 (config-driven verticals) pays off first** — 12 MCP scenarios
  are much cheaper to author if a vertical is YAML rather than a Python subclass.

## Recommended sequence

**PRD-012 → PRD-014 (CI lane) → PRD-013 (5-scenario slice) → PRD-015 → PRD-008 → PRD-013 (rest) → PRD-016**

Rationale: fix what a first user sees (012, 014), then take the uncontested ground while
it is uncontested (013), then make the cost/statistics story defensible (015 → 008). PRD-016
presupposes adoption, so it comes last.
