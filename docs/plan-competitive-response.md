# Competitive-response actions for agentaudit

## Context

A competitive research pass (Aug 2026) compared agentaudit against deepeval, garak, PyRIT,
Giskard, AgentDojo/Inspect AI, and guardrails-ai. Two findings matter:

1. **The gaps it names are mostly real** — no competitor verifies real side effects against a
   black-box endpoint, none generates compliance evidence, and none separates "the attack
   failed" from "the agent still did its job."
2. **Two of its recommendations are already shipped here and invisible** — OWASP Agentic (ASI)
   mapping exists in `core/compliance.py`, and per-test run progress landed in commit 400595b.
   The README claims neither.

The intended outcome is a small set of additive changes that (a) fix the one bug blocking the
most common real-world agent endpoint, (b) make already-built strengths visible, and (c) add
the one methodology axis that puts agentaudit ahead of garak/PyRIT rather than merely level.

Everything below was verified against the working tree on `feat/cli-run-progress`.

---

## Already done — do not rebuild

| Research recommendation | Reality |
|---|---|
| "Add OWASP Top 10 for Agentic mapping" | `core/compliance.py:111-118` maps ASI01/02/03/05/06/09 off the pack namespace; `UNCOVERED` at :122-127 declares the other four with honest reasons. All 10 accounted for. There is a second axis (`OWASP_LLM_BY_CATEGORY`, :99-108) too. **Action: one README row, no code.** |
| "Progress feedback during runs" | `cli.py:281-288` emits `[i/N] <id>` to stderr via `runner.run`'s `on_test` callback. **One gap:** suppression is keyed on `format != "json"`, which breaks the moment a second machine format exists — fixed as part of Task 3. |

## Not doing

- **MCP support** — new spec type, new transport dep, and an egress story that
  `core/egress.py`'s host-allowlist + public-IP model does not cover. Defer until a named user
  asks. Task 1 likely absorbs most demand currently attributed to "adapter coverage."
- **New verticals (CRM/healthcare/ticketing)** — more expensive than `CLAUDE.md:233-235` admits
  (see Task 5 note). Depth beats breadth right now.
- **"Reliability hardening"** — no named defect. `runner.py` already cannot raise, the gate
  already fails closed, `pip-audit` already runs weekly.

---

## Task 1 — Array indexing in `_extract_path`

**Why first:** every OpenAI-compatible endpoint returns `choices[0].message.content`.
`backend/agentaudit/core/agent.py:90-100` splits on `.` and only ever does
`isinstance(current, dict) and part in current`, so that path returns `(False, None)` →
`error="response_path_not_found"` (agent.py:176-184). Broader adapter coverage is moot while
the adapter that exists cannot parse the most common response shape in the world.

**Files:** `backend/agentaudit/core/agent.py` (one function).

Keep the dotted split. Per part, peel a trailing `[n]` (or `[n][m]`) into name + index list with
one regex: dict lookup for the name, then per index check `isinstance(current, list)` and
bounds. Any miss still returns `(False, None)` — the `response_path_not_found` contract is
unchanged. Non-negative indices only; mark with a `# ponytail:` comment naming the limit.

No `jsonpath-ng`: a new runtime dep for what ~10 lines do, and it would silently accept
filter/wildcard syntax the target-config contract does not document.

**Test:** table in `tests/test_agent.py` — `$.choices[0].message.content` hit, out-of-bounds →
not found, index-on-dict → not found, existing `$.text` regression. Plus one end-to-end through
the stub transport in `tests/test_http_agent.py`.

**Same task, 2 lines:** add a commented OpenAI-shaped `text_path` to
`agentaudit/config/my-agent.example.yaml` — it is the documented onboarding template and shows
only the trivial case today.

---

## Task 2 — README: telemetry guarantee, ASI claim, stale ref

**Why:** the zero-telemetry property is verified true and completely unstated. `httpx` is
imported in exactly one file (`core/agent.py:12`) and that rule is *enforced* by
`.claude/rules/dependency-boundaries.md` — architecturally guaranteed, not merely
currently-true. This is the #1 complaint pattern across deepeval and guardrails-ai and the one
claim no VC-backed competitor can match.

**Files:** `README.md`, `agentaudit/config/treasury-http.yaml`.

1. **Data-residency subsection** near the compliance section. State what the code does, with
   paths: no analytics/crash reporting/update checks; exactly three outbound destinations — the
   agent under test (`core/agent.py`), the operator's own OIDC IdP if enabled
   (`frontend/agentaudit/web/auth.py:311`), and DNS (`core/egress.py:42`); evidence stays in a
   local SQLite file; no external CDN in any template. Write it as verifiable fact, not a
   promise — this README already concedes garak has broader probes, so a puffed claim would be
   off-key beside it.
2. **Two rows in the comparison table** (`README.md:171-185`): `Telemetry / phone-home` →
   `none (enforced: httpx confined to one file)`, and `OWASP Agentic (ASI)` →
   `6 mapped, 4 declared uncovered`. The second claims work that already exists.
3. **LangChain / CrewAI snippets** — both already work through `CallableSpec`
   (`module:factory`, where the factory returns the agent fn and may accept a `sandbox` kwarg,
   `core/agent.py:46-49`). Add a ~3-line factory example for each. The gap is documentation,
   not code; do not add framework-specific spec types.
4. **Fix the stale ref:** `agentaudit/config/treasury-http.yaml:9` points at deleted
   `examples/stub_endpoint.py`, which `CLAUDE.md:174` says must not return. Repoint at
   `demo-stub-http.yaml` + `tests/test_http_agent.py`. Leave `docs/archive/*` alone.

**Test:** none — prose.

---

## Task 3 — SARIF export

**Why:** requested by Giskard's community, absent across this category, and cheap here — the
extension seam is a dict and SARIF is JSON, so no new dep (`reports/json.py` is the precedent).
It also makes the existing ASI mapping visible in the GitHub Security tab, where security teams
already look.

**Files:** new `backend/agentaudit/reports/sarif.py`; `reports/__init__.py` (one import, one
`_RENDERERS` entry, one `__all__` entry); `cli.py:286-288`.

SARIF 2.1.0, one `run`, `tool.driver.name = "agentaudit"`:

- **rules** — one per `test_id`; `properties.tags` carries the OWASP/ASI/LLM codes from
  `compliance.controls_for(result)`.
- **results** — `failed` and `error` only. SARIF is a finding format; JUnit already covers the
  full pass/fail roster.
- **level** — from `Risk`, not status: `critical|high → error`, `medium → warning`,
  `low → note`. `Status.error → warning` regardless — a harness error is not a finding about
  the agent.
- **message.text** — first failing assertion detail. Reuse `reports/junit.py`'s existing
  helper rather than rewriting it.
- **locations** — no source file exists. Use the pack YAML path if the loader carries one,
  else a single `artifactLocation.uri = "agentaudit"` placeholder. Do not invent line numbers.
- **partialFingerprints** — `{"agentauditTestId": test_id}`, so GitHub dedupes findings across
  runs. This one line is the difference between useful and noisy.

**Redaction:** control-plane renderer consuming an already-redacted `RunResult`. Put detail in
`message.text` only; do **not** emit `request`/`response` even though redacted —
`EvidencePolicy` may have dropped them to `None`, and SARIF is uploaded to a third party.

**Progress-suppression fix (same task):** replace the `format != "json"` checks at
`cli.py:286-288` with a module-level `_MACHINE_FORMATS = {"json", "sarif"}`. Simplest correct
scope: `run` does not accept `sarif`; `agentaudit report --format sarif` is the path, matching
how `compliance` already works.

**Test:** `tests/test_reports.py` — parses as JSON, `version == "2.1.0"`, a passed test yields
no result, a failed critical → `level == "error"`, fingerprints present, rule tags carry ASI
for an `agentic.tool_misuse.*` id. Plus one `tests/test_cli.py` case for `--format sarif`.

---

## Task 4 — Dogfood agentaudit in its own CI

**Why:** the tool emits JUnit XML and an EU AI Act compliance report; its own CI uploads
neither and never runs itself. Cheapest credibility fix available, and it *proves* Tasks 1 and
3 rather than asserting them.

**Files:** `.github/workflows/ci.yml` — one new `dogfood` job.

checkout → setup-uv → `uv sync --frozen --extra dev` → `agentaudit run agentaudit/packs/core
--target agentaudit/config/treasury-agent.yaml` → `agentaudit report --run <id> --format sarif
--out agentaudit.sarif` → `github/codeql-action/upload-sarif` → `actions/upload-artifact` for
the JUnit and compliance outputs. SHA-pin the new actions like every other action in this file.

Three things to get right:

- **`security-events: write` must be job-scoped.** The top-level `permissions: contents: read`
  (`ci.yml:10-11`) is deliberate least-privilege; do not widen it globally.
- **Do not add `dogfood` to the `required` gate** (`ci.yml:87-103`). The demo agent's score is
  test *content* — a pack tweak must not red the build. Upload as evidence, gate on nothing.
  `agentaudit run` exits 1 on a failed gate, so the run step needs `continue-on-error` or an
  explicit `|| true`.
- **Run-id capture:** `run` writes to SQLite and `report` needs the id. `run --format json`
  already emits `run_id` (`cli.py:294-307`), so pipe it through `jq`. Note `--format json`
  suppresses progress by design; that is correct for CI.

---

## Task 5 — Utility / security split scoring

**Why:** AgentDojo's core methodological point — measuring whether a defense also broke the
agent's ability to do its job — is treated as more rigorous than attack-only scoring, and
garak/PyRIT do not do it. Today an agent that refuses *everything* scores identically to one
that correctly refused an injection while still completing the legitimate task.

**Confirmed seam:** the benign tests already exist and are mis-scored.
`agentaudit/packs/treasury/approved_payment.yaml:13` asserts `payment_created` — the agent is
supposed to *succeed* — and it lands in the same weighted denominator as every attack. This is
a partition of existing data, not new test content.

**Do not add a `Category`.** That would touch `scoring.py` weights, `catalog.py`, and
`compliance.py:CONTROLS_BY_CATEGORY` — which is a bare subscript at `compliance.py:137`, so a
missing key raises `KeyError` at report time. Compliance is required to fail closed, not crash.
Wrong seam.

**Use a reserved tag.** `TestCase.tags` exists (`schema.py:64`), is authored in every shipped
pack, and `catalog.py:23 DOMAIN_TAGS` sets the reserved-tag precedent. Reserve `utility`.

Files and changes:

- **`core/schema.py`** — `TestResult` (:107-121) does not carry `tags`, so scoring cannot see
  them. Add `tags: list[str] = Field(default_factory=list)`. Additive with a default, so every
  persisted row and existing constructor call keeps working.
- **`core/runner.py`** — populate `tags` where `TestResult` is built from `TestCase`.
- **`core/scoring.py`** — partition `non_skipped` (`:41`) on `"utility" in r.tags`. Existing
  fields keep their current meaning **for the security partition only** — do not silently
  redefine `overall_score`, that breaks comparability with stored runs and `core/regressions.py`.
  Add `utility_score: float | None = None` and `utility_total: int = 0`. `None` means "no benign
  tests ran," which is honestly different from `0.0` and must not render as a failure.
- **`gate_passed` unchanged** — ship the measurement first. Picking a threshold off two benign
  tests would be guessing.
- **Packs** — tag `treasury/approved_payment.yaml` and `email/phishing.yaml` with `utility`,
  then add 2-3 benign cases per vertical so the number means something. Pure YAML.
- **Renderers** — `md.py` and `html.py` show the figure; the JSON formats get it free through
  Pydantic; JUnit and SARIF need nothing.

**Test:** `tests/test_scoring.py` — utility results excluded from `overall_score`; no utility
tests → `None`; only utility tests → the security axis behaves like the existing empty-run
fail-closed path (`scoring.py:49-63`). Plus a `tests/test_store.py` round-trip for the new
field, then the **full suite** — `CLAUDE.md` ladder rung 4, since `schema.py` is a contract.

---

## Sequencing

```
Task 1  array indexing (+ example-config line)     independent — ship first
Task 2  README (telemetry, ASI, shims, stale ref)  independent, no code
Task 3  SARIF (+ progress-suppression fix)         independent
Task 4  CI dogfood                                 needs Tasks 1 and 3
Task 5  utility scoring                            own branch, schema change
```

Tasks 1-3 are parallel and land as separate PRs.

## Verification

Per `CLAUDE.md`'s validation ladder — on Windows, call pytest as a module, never the console
script:

- **While iterating (Tasks 1-4):** `bash tools/validate.sh --affected`
- **Task 1:** `python -m pytest tests/test_agent.py tests/test_http_agent.py`
- **Task 3:** `python -m pytest tests/test_reports.py tests/test_cli.py`
- **Task 5:** `python -m pytest tests/test_scoring.py tests/test_store.py tests/test_schema.py`,
  then the full suite (~150s) — mandatory, it touches `schema.py`.
- **Before declaring any task done:** `bash tools/validate.sh`

End-to-end manual checks:

```bash
# Task 1 — should now resolve an OpenAI-shaped response path
agentaudit run agentaudit/packs/core --target agentaudit/config/treasury-agent.yaml

# Task 3 — valid SARIF, ASI tags present on agentic rules
agentaudit run agentaudit/packs/agentic --target agentaudit/config/treasury-agent.yaml
agentaudit report --run <run_id> --format sarif --out /tmp/a.sarif
python -c "import json;d=json.load(open('/tmp/a.sarif'));print(d['version'],len(d['runs'][0]['results']))"

# Task 5 — utility_score present and separate from overall_score
agentaudit report --run <run_id> --format json | python -m json.tool | grep -i utility
```

**Task 4 verification is the CI run itself:** open the PR, confirm the `dogfood` job uploads
SARIF, findings appear in the GitHub Security tab, and the `required` gate stays green
independent of the dogfood run's score.

## Notes for the implementer

- `CLAUDE.md:233-235` claims a new domain "requires no change to `core/`." That is true for
  registration and **false for usefulness**: `catalog.py:23 DOMAIN_TAGS` is a frozenset, so a
  tag outside it makes the pack domain-agnostic and it runs against every agent. If a vertical
  is ever built, correct that line — it understates the cost.
- `AssertionContext.diff` is populated by `runner.py` and read by no shipped assertion. Not in
  scope here; worth knowing before anyone assumes it is load-bearing.
