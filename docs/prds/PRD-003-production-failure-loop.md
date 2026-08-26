# PRD-003: Production-Failure → Regression Loop

**Type:** Feature · **Priority:** 3

## Problem

The most consistent practitioner complaint about agent testing is that
regression suites only contain *anticipated* failures. The bugs that actually
burn teams are emergent: "the agent goes off the rails in scenarios you didn't
anticipate" (r/AI_Agents). Today the workflow to capture those is manual:
reproduce the incident, hand-write a YAML case, remember which category it
belongs to, keep it maintained. Most production failures therefore never
become regression tests.

agentaudit already has 80% of the machinery:

- A human-review pipeline for machine-generated cases (`core/evolve.py`,
  novelty archive `core/archive.py`, dashboard promote/reject endpoints at
  `frontend/agentaudit/web/api.py:804,836`).
- Test-case authoring in the SPA.
- Deterministic YAML pack format validated at load time.

What is missing is an **ingest path**: turn a pasted failing conversation /
tool trace into a draft test case.

## Evidence

- Arthur (Jun 2026), Decagon glossary, Agno docs all describe
  "capture traces → golden dataset → gate CI" as best practice; none of the
  open-source harnesses automate the trace→case conversion.
- Reddit r/AI_Agents thread "How is everyone handling agent regression testing
  in CI" — top answer themes are manual spot-checking and spreadsheet tracking.
- agentaudit's own `evolve` design (generate → validate → review → admit)
  already solves the trust problem for auto-generated tests; incidents deserve
  the same treatment.

## Goals

1. **Incident ingest** (v1): paste or upload a transcript (user/agent/tool
   turns) via CLI (`agentaudit incident add`) or the dashboard; the system
   drafts a YAML case with input, expected-behavior assertions inferred from
   the failure annotation, category suggestion, and provenance metadata.
2. Drafts enter the existing review queue with status `provisional` and the
   same expiry/promotion semantics generated attacks use
   (`core/archive.py:expired`, `promoted_id`) — nothing is auto-baselined.
3. One click (or one flag) replays the incident against the current agent to
   confirm it reproduces before admission.

## Non-goals

- Automatic assertion synthesis without human review (violates the repo's
  fail-closed, reviewed-evidence philosophy).
- Live production tracing integrations (LangSmith/Langfuse connectors) — v2.
- Storing raw customer data; ingest runs the redactor over everything first.

## User stories

- As an on-call engineer, after an incident I paste the redacted transcript
  into the dashboard, annotate "should have refused the forward", and get a
  draft case in the review queue within seconds.
- As a team lead reviewing the queue, I see reproduction status (does the
  current agent still fail?) next to each draft before promoting it into the
  permanent pack.
- As a compliance owner, every admitted incident-derived case carries
  provenance (date, source, reviewer) that flows into reports.

## Requirements

1. New module `backend/agentaudit/core/incidents.py`: parse transcript
   formats (plain text turns + JSON tool-trace v1), extract final user input
   and per-turn tool events, map tool events onto sandbox facts where a
   matching domain sandbox exists.
2. Redaction-first: `core/redaction.py` applied at ingest boundary and again
   at persistence (dual-pass pattern used by the runner).
3. Dashboard route(s) follow web-module rules: principal required, no file
   writes from web layer (per `frontend/agentaudit/web/CLAUDE.md`).
4. Replay uses the standard runner so timeouts, pass^k folding, and evidence
   storage behave identically to normal runs.
5. Tests: `tests/test_incidents.py` (parsing, redaction, dedupe against
   archive ids) + API tests in `tests/test_web.py`.

## Success metrics

- Median time from incident transcript to promoted regression case < 5 minutes.
- ≥ 70% of drafted cases survive review (drafts must be high-signal, not noise).
- Every promoted incident case appears in the compliance report's coverage.

## Open questions

- Transcript format support priority (OpenAI-style messages? LangChain dumps?
  free text?).
- Should replay-failure-to-reproduce block promotion or just warn?
