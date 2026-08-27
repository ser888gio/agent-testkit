# Task 4 — Presentation readiness checklist

**Skill availability note:** no pitch-deck, demo-scripting, or README-polish skill is
installed in this environment. Closest partial fits: `impeccable` (frontend/UX polish —
applies to the dashboard demo surface only) and `ogilvy-copywriting` (persuasive copy —
applies to README/landing headlines). Neither covers demos/pitches end-to-end, so this
checklist was produced manually. Note the repo already contains `PRD-005`
(presentation-readiness: remove committed build artifacts/databases/caches) and a
`video-presentation.md`, `landing/`, and Docusaurus `website/` — start there.

## Readiness checklist (before demoing/pitching)

1. **Truthful first run (blocker).** Demo must run exactly what the README says. The bare
   `run core` false-failure bug must be fixed and merged (branch
   `fix/core-skip-without-sandbox` / PRD-006) — a live demo showing three fake jailbreak
   failures on a harmless agent destroys trust in front of an audience.
2. **Docs match reality (blocker).** Sample outputs in README/quickstart now match real
   category names and counts (branch `fix/readme-quickstart-output`); re-verify after merge.
3. **The 90-second money shot.** Script the demo around the differentiator:
   safe agent → all green; overtrusting agent → 7 critical failures, `Gate: BLOCK`, exit 1;
   show one sandbox diff as evidence ("the bank says a payment happened"). This sequence is
   verified working today.
4. **Judge-free positioning line.** Add one sentence to the README above the fold: gates on
   deterministic side-effect assertions, no LLM-judge variance (backed by pain-points.md #2).
5. **Compliance report in the demo path.** Show `--format compliance` output for 30 seconds;
   it's the rarest capability in OSS (pain-points.md #7).
6. **Screenshots/GIFs.** Terminal table + dashboard RunDetail + compliance report; none are
   currently in the repo.
7. **Hosted try-it path.** A Codespace/Colab or container that boots the stub agent +
   agentaudit with zero local install; current quickstart requires clone+install.
8. **Repo hygiene per PRD-005.** Remove committed `dist/`, `build/`, `.pytest_cache/`,
   `agentaudit.db`/`agentkit.db` artifacts before any public link-sharing.
9. **Limits page linked from README status block.** `website/docs/limits.md` already exists
   and is honest; make it impossible to miss (the "Not built" iterative-attack row should be
   visible to evaluators up front, not discovered later).
10. **Comparison table refresh.** Update the README "How it compares" table against
    RAMPART and promptfoo-trajectory specifically (landscape.md finding #1/#2), not just
    garak/promptfoo-generic — sophisticated evaluators will ask.
