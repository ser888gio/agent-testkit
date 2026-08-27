# PRD-007 — Docs must not show output the tool cannot produce

**Type:** Fix · **Status: IMPLEMENTED** (branch `fix/readme-quickstart-output`, commits `3916c22`, `2288be6`)

## Problem
README and website quickstart showed sample CLI output containing a `jailbreak` category row
— impossible: the `Category` enum has no such value (those tests are `prompt_injection`) —
plus row counts inconsistent with the shipped pack (data_leakage 3 vs actual 4). Anyone who
runs the tool once sees the docs don't match reality; combined with PRD-006's false failures,
the docs actively miscalibrated expectations. Found during Task 2 user-path walkthrough;
independently confirmed by running the bare core pack.

## Proposed solution
Replace stale samples with internally consistent output matching real categories/counts
(20 tests: data_leakage 4, endpoint_contract 3, performance 1, prompt_injection 6,
reliability 6), explain the SKIP column, align dev-install wording with repo conventions
(`uv sync --extra dev` alternative), fix the same table in website/docs quickstart, and
reword "needs no sandbox" to describe skip-until-sandboxed behavior accurately.

## Success criteria
- No category name or count in README/website that the schema/packs cannot produce (grep-verifiable).
- Sample tables sum to their headers; SKIP explained at first occurrence.
- ✅ Met on the implementation branch (both files corrected; grep clean).

## Priority & effort
P1 — cheap credibility repair for a pre-traction project whose only channel is its README
· Effort: S (done)

## Open questions
- `website/docs/guides/choose-a-pack.md:15` still says core "asserts only on what the agent
  said" — needs the same nuance; left out of the implemented branch to keep it scoped.
