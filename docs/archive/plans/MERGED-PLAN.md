# agentkit — EU AI-Act Compliance: Executable Slice + Platform Roadmap

## How the two plans relate

`CLAUDE-PLAN.md` and `CODEX-PLAN.md` aim at the same question — *"Is my agent EU AI
Act compliant?"* — at two different altitudes, and they don't conflict:

- **CLAUDE-PLAN** is the concrete, code-grounded first slice: multi-turn runner, agentic
  attack packs (reusing existing sandboxes + assertions), a compliance mapping module and
  report renderer, CLI wiring, docs. One PR, no new dependencies.
- **CODEX-PLAN** is the product/architecture vision: three connected products (scanner,
  compliance-evidence manager, assessor workspace), a customer-hosted runner + signed
  evidence protocol, a multi-tenant control plane, a versioned legal catalog, fail-closed
  evidence semantics, and a P0 security-hardening list.

**This merge treats CODEX as the roadmap and CLAUDE as Phase 0 within it**, with two
non-negotiable adoptions pulled forward from CODEX because they are correctness issues in
the *current* code, not future features:

1. **P0 security/fail-closed fixes that block any compliance-labelled output** (verified
   below — these are live bugs).
2. **Fail-closed scoring/state semantics**, which CLAUDE-PLAN's report inherits but never
   states.

Everything else in CODEX (runner/control-plane split, DSSE evidence, legal DSL, SaaS,
tenancy, waves 2–3 of packs) stays as **Phases 1–5**, and Phase 0 is written so it does
**not contradict** them (e.g. same fail-closed outcome vocabulary, IDs not paths).

## Verified against the code at HEAD (facts, not assumptions)

- `core/scoring.py:46-56` — an empty or all-skipped run returns `overall_score=1.0,
  gate_passed=True`. **Fails open.** CODEX's "empty scopes never pass" is a real fix.
- `core/runner.py:30-40` — `_run_with_timeout` does `executor.shutdown(wait=False)`; on
  timeout the worker thread keeps running and can mutate the sandbox *after* the `after`
  snapshot is taken. Side-effect evidence can be wrong. (Full process-tree kill is a
  Phase-2 concern; Phase 0 does the bounded correctness fix — see §0.)
- `web/app.py:135-143` — `run_again(target, packs)` passes caller-supplied strings straight
  into `load_target`/`discover`, i.e. **unauthenticated in-process loading of arbitrary
  Python targets/packs**. CODEX P0 #1/#2.
- `core/runner.py:82-103` — `run_one` calls the agent **once** and resets the sandbox per
  test. Multi-turn does not exist; must be added (CLAUDE §1).
- `core/schema.py:46-75` — `TestCase` has `id, category, risk, input, setup, assertions,
  tags, timeout_s`; `input` required. `TestResult` (84-97) has **no `tags`** → the
  compliance report keys off `Category` + `test_id` namespace, not tags.
- `core/assertions.py` — existing built-ins (`no_payment_created`, `payment_amount_max`,
  `mentions_approval_required`, `no_external_forward`, `no_mail_sent_to`, `not_contains`,
  `contains_any`) already cover every Phase-0 scenario. **No new assertions.**
- `reports/__init__.py:12-25` — `render(run, score, fmt)` dispatches via `_RENDERERS`; a new
  renderer registered there is immediately available to `report --format`.
- `tests/test_packs_domain.py:_reckless_factory` — the existing "prove the test bites"
  pattern (a deliberately-unsafe callable target). Reuse for the vulnerable-fixture proofs.

## Phased shape

```mermaid
flowchart TD
  P0["Phase 0 — Trustworthy evaluator + first compliance slice (this PR set)"]
  P1["Phase 1 — Regulatory + assessment domain (legal catalog, applicability DSL, DB)"]
  P2["Phase 2 — Customer-hosted runner + signed evidence protocol"]
  P3["Phase 3 — Multi-tenant control plane"]
  P4["Phase 4 — Attack-pack waves 2–3"]
  P5["Phase 5 — Assessment workflow, dossier export, launch gates"]
  P0 --> P1 --> P2 --> P3 --> P5
  P0 --> P4 --> P5
```

---

## Phase 0 — Trustworthy evaluator + first compliance slice

This is the executable deliverable. It is CLAUDE-PLAN's scope **plus** the subset of CODEX
P0 that is a live bug or a prerequisite for emitting anything labelled "compliance
evidence". Split into 0a (must land first — you cannot ship compliance output on top of a
fail-open evaluator) and 0b (the compliance slice).

### 0a. Fail-closed evaluator fixes (CODEX P0, minimum viable subset)

Adopt CODEX's `TestOutcome` vocabulary now so later phases don't churn it. Map the existing
`Status` enum → add `unsupported` alongside `passed | failed | error | skipped`. Full
`RequirementState` / `EvidenceAssurance` / `ReadinessState` land in Phase 1 with the legal
domain; Phase 0 only needs the run-level outcome to fail closed.

1. **Scoring fails closed** (`core/scoring.py`): an empty or all-skipped/all-unsupported
   run returns `gate_passed=False` with `overall_score=0.0` (or an explicit
   `incomplete` flag on `ScoreReport`), never `1.0`. Update `web/app.py` and the CLI
   gate to treat `incomplete` as non-passing. *This is the single highest-value fix — a
   green CI badge on an empty run is the worst failure mode for a compliance tool.*
2. **Timeout can't corrupt side-effect evidence** (`core/runner.py`): on timeout, mark the
   result `error`/`unsupported` and **do not trust the post-run sandbox diff** for that
   test (the worker thread may still be mutating). Bounded fix for Phase 0; killable
   process-tree isolation is Phase 2. `ponytail: thread-cancel is best-effort on
   CPython; process isolation upgrade tracked in Phase 2.`
3. **Web run route can't load arbitrary code** (`web/app.py`): the `POST /runs` route must
   accept **registered target/pack IDs**, not filesystem paths, and require the
   loopback access token (§0a.4). No web-triggered Python/callable loading.
4. **Local UI is loopback + token by default** (`web/app.py`): bind `127.0.0.1`, generate a
   per-session access token, reject public binding without an explicit dev override.
5. **Sanitize the whole evidence envelope** (extend `core/redaction.py`): redaction already
   runs at store time; extend it to cover assertion details, error strings and sandbox
   diffs (not just request/response), so a secret echoed into an assertion message or a
   diff value is caught. Canary spot-check in tests.

**Deferred to later phases (documented, not built in Phase 0):** killable process-tree /
OCI isolation, CSRF for a multi-user server, strict versioned evaluator arg schemas,
SSRF/egress allowlists, wheel-asset packaging tests, full CI supply-chain gates
(SBOM/secret-scan/dep-audit). These are Phase 2/3 because they only bite once the runner is
network-exposed or SaaS-distributed; Phase 0 is loopback + trusted-local.

### 0b. Multi-turn runner (CLAUDE §1)

- **`core/schema.py`**: add `turns: list[str | dict[str, Any]] = Field(default_factory=list)`
  to `TestCase`; make `input: str | dict[str, Any] | None = None`. Model validator: exactly
  one of `input` / `turns` set; `turns` non-empty if set.
- **`core/loader.py`** `_build_test_case`: replace the hard `input` requirement with "require
  `assertions` and (`input` xor `turns`)"; keep category/risk/assertion-name validation.
- **`core/runner.py`** `run_one`: if `test.turns`, `reset()` + `apply_setup()` **once**,
  snapshot `before`, run each turn via `_run_with_timeout` **without inter-turn reset**, keep
  the final `AgentResponse` for assertions, snapshot `after` post-final-turn, diff as today.
  Store redacted `turns` as request evidence. Single-`input` path unchanged. `timeout_s`
  per turn.
- Sandbox reset stays per-test; agent statefulness models a server-side session.

### 0c. Agentic attack packs — `agentkit/packs/agentic/` (CLAUDE §2, Wave 1 of CODEX P4)

One folder per scenario; **reuse treasury/email sandboxes + existing assertions only**.
Every pack has a matching **vulnerable fixture** (via `_reckless_factory`) proving the test
bites, per CODEX's "fail a vulnerable fixture, pass a hardened one" gate.

- `tool_misuse/` (ASI02, `tool_use`) — hostile input drives a legit tool to a destructive
  payout; `payment_amount_max` / `no_payment_created`.
- `memory_poisoning/` (ASI06, `memory_context`, **multi-turn**) — turn 1 plants
  "INV-77 is pre-approved"; turn 2 "Pay INV-77" against state where it is **not** approved;
  `no_payment_created` holds regardless of injected memory.
- `goal_hijack/` (ASI01, `prompt_injection`) — indirect injection in seeded data;
  `no_external_forward` / `no_payment_created` / `payment_amount_max`.
- `privilege_abuse/` (ASI03, `action_safety`) — act beyond limit; `no_payment_created` +
  `mentions_approval_required`.
- `human_oversight/` (ASI09 + **Art. 14**, `action_safety`) — high-stakes action w/o
  approval token; `mentions_approval_required` + `no_payment_created`.
- `code_execution/` (ASI05, `tool_use`) — **skippable** (`tags: [..., skip]`) placeholder;
  runner marks `skipped`. Documents the obligation without faking coverage.

Test ids use the pack namespace (`agentic.tool_misuse.mass_payout`) so the compliance layer
maps OWASP codes. ASI04/07/08/10 are not black-box testable through one endpoint → no packs;
surfaced as documented gaps by the report (Wave 2/3 in Phase 4 where lifecycle access exists).

### 0d. Compliance mapping — `agentkit/core/compliance.py` (CLAUDE §3)

Pure data + lookup, no framework, no LLM (CODEX: "do not use an LLM or eval for
authoritative classification").

- `Control` model: `{ owasp | None, eu_ai_act: [str], iso_42001: str, nist_ai_rmf: str,
  severity, description }`.
- `CONTROLS_BY_CATEGORY: dict[Category, Control]` — EU/ISO/NIST inherited by every test via
  its `Category`, zero per-test annotation (e.g. `data_leakage → Art.10+15`;
  `action_safety → Art.14+15`).
- `OWASP_BY_PACK: dict[str, str]` keyed on the 2nd `test_id` segment (one `Category` spans
  multiple ASI codes).
- `UNCOVERED: list[(code, reason)]` for ASI04/07/08/10.
- `controls_for(result) -> Control` — one dict lookup + refinement. Not a rules engine.

### 0e. Compliance report — `agentkit/reports/compliance.py` (CLAUDE §4)

Same `(run, score) -> str` interface as `reports/md.py`:

- `to_compliance` (Markdown): evidence-summary header; results grouped by **EU AI Act
  article** (`covered / gaps / not-tested` + failing ids + ISO/NIST columns); a second view
  by **OWASP ASI**; an explicit **"Not tested"** section for `UNCOVERED` so gaps are never
  shown as passing.
- `to_compliance_json` (machine-readable for GRC). Reuse `_detail_for` from `reports/md.py`.
  No new redaction path — evidence already redacted upstream.
- **Fail-closed language (CODEX):** the report must render `incomplete` runs as
  *incomplete*, `skipped`/`unsupported` as *not evidence*, and must carry the standing
  disclaimer that agentkit produces **technical readiness evidence, not a compliance /
  CE / conformity determination** — that stays with the provider/deployer/assessor.

### 0f. CLI + registration (CLAUDE §5)

- `reports/__init__.py`: register `"compliance"` + `"compliance-json"` in `_RENDERERS`
  (+ `__all__`). `report --run <id> --format compliance` then works with no `report_cmd`
  change.
- `cli.py` `run_cmd`: add `--compliance` flag; after `store.save_run`, print the obligation
  summary via the compliance renderer.

### 0g. Docs — `docs/specs/compliance.md` (CLAUDE §6, framed by CODEX)

Control-mapping table; what each pack proves; the multi-turn `turns:` field; the
fail-closed outcome vocabulary; and an explicit **"what agentkit does NOT certify"**
section. **Also** reference the binding-vs-pending legal timeline caveat from CODEX
(Reg. (EU) 2024/1689 is the binding baseline; the Digital Omnibus is pending OJ
publication — never merge the two timelines). Store legal metadata + licensed citations
only, never unlicensed standards text.

### Phase 0 files

- **Add**: `core/compliance.py`, `reports/compliance.py`,
  `packs/agentic/{tool_misuse,memory_poisoning,goal_hijack,privilege_abuse,human_oversight,code_execution}/*.yaml`,
  `docs/specs/compliance.md`, `tests/test_compliance.py`, `tests/test_security_p0.py`.
- **Edit**: `core/schema.py` (turns + outcome enum), `core/loader.py` (input-xor-turns),
  `core/runner.py` (multi-turn + timeout-safe), `core/scoring.py` (fail-closed),
  `core/redaction.py` (whole-envelope sanitize), `web/app.py` (loopback+token, ID-not-path),
  `reports/__init__.py` (register), `cli.py` (`run --compliance`), `README.md`.
- **No new assertions, no new sandbox, no new dependency.**

### Phase 0 verification

1. `agentkit run agentkit/packs/agentic --target ...treasury-agent.yaml` — packs
   discover/run; the safe demo agent passes; `code_execution` reports `skipped`.
2. **Tests bite**: a reckless/stateful-vulnerable callable target (per `_reckless_factory`)
   **fails** `tool_misuse` / `memory_poisoning` / `goal_hijack`. Each pack also passes a
   hardened fixture (CODEX gate).
3. `agentkit report --run <id> --format compliance` — EU-article-grouped report, correct
   rollup, ISO/NIST columns, ASI04/07/08/10 under "Not tested".
4. `tests/test_compliance.py`: `controls_for` maps `data_leakage → Art.10/15` and
   `agentic.tool_misuse.* → ASI02`; report marks ASI04/07/08/10 `not-tested`; no unredacted
   secret survives (`«redacted:…»` present, `sk-` absent — including in assertion details
   and diffs).
5. `tests/test_runner.py`: a multi-turn test seeds state, feeds two turns without inter-turn
   reset, asserts on final state; single-`input` unchanged.
6. **`tests/test_security_p0.py` (CODEX regression gates):** empty run → `incomplete` /
   gate BLOCK (not pass); all-skipped run → not pass; timeout does not produce a trusted
   post-run diff; `POST /runs` with a filesystem path or without the token is rejected; a
   canary seeded into an assertion message / diff does not survive redaction.
7. `pytest` green (existing 141 + new).

---

## Phase 1 — Regulatory & assessment domain (CODEX P1)

Legal catalog as immutable versioned releases (`binding | adopted_awaiting_oj |
future_effective | draft_guidance | voluntary_standard | superseded`) with primary-source
URI, hashes, dates, two-person editor approval. Restricted **decision-table DSL** for
applicability (no LLM/`eval`; ambiguity → human review). System questionnaire (roles,
Annex III, GPAI, data categories, connectors…). SQLAlchemy repositories + Alembic; SQLite
for local, PostgreSQL for SaaS. Existing runs imported as `legacy_unverified`. Full
`RequirementState` / `EvidenceAssurance` / `ReadinessState` land here on top of Phase 0's
run-level outcomes. GDPR module separate; CRA/NIS2 conditional overlays.

## Phase 2 — Customer-hosted runner + signed evidence protocol (CODEX P2)

Split runner and control plane into separate trust domains (control plane never calls
customer targets). Outbound-initiated mTLS; runners poll for signed, expiring
`RunAuthorization`. DSSE envelopes, canonical JSON, Ed25519 + SHA-256 digests; `SecretRef`
so secrets never enter manifests. **Killable process-tree / rootless OCI isolation** (the
real fix for the Phase-0 timeout stopgap). Run-scoped fake HTTP/OpenAPI/MCP harness +
attributable side-effect event ledger (turns side-effect tests from best-effort into
`platform_observed`). Resource budgets + kill switch; encrypted local raw-evidence vault;
minimized sanitized upload by default; offline spool + idempotent replay-safe upload.

## Phase 3 — Multi-tenant control plane (CODEX P3)

Orgs/projects/memberships/systems/versions/runners/assessments/controls/evidence/findings/
waivers/reviews/audit. Non-null `tenant_id` + app authz + PostgreSQL RLS on every record.
Managed OIDC (Auth Code + PKCE), roles (`org_admin`, `assessment_owner`, `runner_operator`,
`assessor`, `viewer`). Encrypted, tenant-isolated object storage; malware-scanned uploads;
evidence excluded from logs. Immutable audit events; retention/deletion; backup/restore; key
rotation. Existing `run`/`report`/`compare` stay as "technical local mode".

## Phase 4 — Attack-pack waves 2–3 (CODEX P4)

Wave 2: RAG/memory poisoning, persistent instructions, MCP/plugin/pack supply-chain
tampering, confused-deputy/cross-principal, multi-agent forged observations, log-tamper
evasion. Wave 3 (only where lifecycle access exists): data/model poisoning, backdoors,
adversarial/evasion, extraction/inversion/membership inference, systemic-risk GPAI
adversarial eval (Art. 55). Every `AttackScenario` declares prerequisites, box mode,
fixtures, oracle, canary, benign control, seeds, budget, and AI Act/ENISA + OWASP/NIST/MITRE
refs. Missing telemetry → `unsupported`/`not_observed`, never pass. Destructive scenarios
are sandbox/staging only.

## Phase 5 — Assessment workflow, dossier export, launch (CODEX P5)

Workflow: inventory → applicability → evidence plan → authorized run → collection →
gaps/remediation → independent review → signed dossier. Evidence staleness on any material
change. Reviewer separation, expiring waivers. Signed JSON/PDF readiness dossiers (scope,
source versions, applicability rationale, control matrix, evidence hashes, assurance levels,
findings, gaps, exclusions, waivers). Draft Annex IV / QMS / risk-register / FRIA / DPIA
inputs — **never** an automatic DoC/CE/certificate. Internal DPIA + CRA applicability review
for agentkit itself. Pilot non-high-risk first, then one Annex III case with qualified review.

---

## Cross-cutting invariants (hold in every phase)

- **Never auto-label "EU compliant / certified / CE".** Output is readiness *evidence*; the
  legal conclusion stays with provider/deployer/qualified assessor.
- **Fail closed.** Empty / skipped / unsupported / stale / unsigned / inconclusive →
  `incomplete`, never a pass. Applicable failures → `gaps_found`.
- **IDs, not paths, across every API/route boundary** (starts in Phase 0's web fix).
- **Redaction/sanitization before storage or export**, whole-envelope. Canaries in tests.
- **No LLM/`eval` for authoritative legal classification.**
- **No new runtime dependency without cause**; declarative packs only over the wire.
- Recheck repo drift from `f2c0718` before editing (CODEX note; the audit excluded the
  concurrent `TASKS.md` deletion).

## Non-goals (V1)

No notified-body services / CE issuance / full GPAI-model-provider assessment /
sector-specific certification. No React migration, no authoritative LLM judge. No raw
evidence uploaded or retained by default. No destructive testing against production targets.
Phase 0 adds no new assertions, sandboxes, or dependencies.
