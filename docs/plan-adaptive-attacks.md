# Adaptive attacks & trajectory evidence — implementation plan

Six features that move agentkit from "fixed packs, final-answer scoring" toward the
"select → attack → mutate → score trajectory" loop in `CLAUDE.md`. Written for agents
starting with no context. Each task cites the files it touches and the contract it must
not break.

## Non-negotiable constraints (read first)

- **Three contracts are cross-cutting**: `core/schema.py` (`TestCase`/`TestResult`/etc.),
  `core/config.py` `TargetConfig`, and the assertion `REGISTRY` in `core/assertions.py`.
  Changing any is a breaking change across `reports/`, `web/app.py`, `cli.py`, `scoring.py`,
  `compliance.py`. Features 2 and 3 touch schema; do them behind additive, optional fields.
- **`runner.py` must never raise.** New branches convert failure to `Status.error`.
- **Dependency direction**: `core → nothing else in agentkit`. New attack/trajectory code
  lives in `core/`. `httpx` stays only in `agent.py`.
- **Redaction runs twice** and must keep covering any new evidence field.
- **New verticals are additive**: new packs are YAML data under `agentkit/packs/`, not code.
- Validate per task with the narrow command; run full suite (`python -m pytest`, ~175s)
  before declaring a schema-touching task done.

## Dependency order

```
F1 attack transforms ──▶ F4 multi-turn adaptive attacks
F3a tool-call ledger ──▶ F3b trajectory assertions
F2 pass^k  (independent)
F5 OWASP LLM mapping (independent)
F6 agentic vuln packs ──▶ needs F3b for its strongest assertions, but ships partial without
```

Parallelizable immediately: **F1, F2, F3a, F5.**
Then: F1→F4, F3a→F3b, F3b→F6.

---

## F1 — Attack methods as composable transforms

**Why:** Packs are fixed content today. An attack *method* mutates an existing test's prompt,
so one method × N existing tests multiplies coverage with zero new hand-written content.

**Files:** new `backend/agentkit/core/attacks.py`, `backend/agentkit/core/loader.py`,
`backend/agentkit/cli.py`, new `tests/test_attacks.py`.

**Design:**
- `attacks.py`: a `TRANSFORMS: dict[str, Callable[[str], str]]` registry, same pattern as the
  assertion `REGISTRY`. Built-ins: `base64`, `rot13`, `leetspeak`, `roleplay_wrap`,
  `unicode_confusable`. Each takes the prompt string and returns a mutated string. Pure
  functions, no state.
- A `apply_attack(test: TestCase, transform_name: str) -> TestCase` that returns a new
  `TestCase` with a derived id (`{id}__{transform}`), the mutated `input`/`turns`, and a tag
  `attack:{transform}`. **Assertions are unchanged** — the point is that an encoded jailbreak
  should still be refused, so the pass/fail bar is identical.
- Expansion happens at load time, not run time: after `discover()`, if a target/run requests
  attacks, expand the test list. Keep `core` pure — the CLI/selection layer decides which
  transforms to apply; `attacks.py` only provides the transforms and `apply_attack`.
- CLI: `agentkit run <pack> --target <t> --attack base64,rot13` expands each test through each
  named transform (originals still run).

**Do not:** mutate assertions, touch `schema.py` (derived id + tag are enough), or apply
transforms to non-string dict inputs silently — skip or error clearly.

**Acceptance:** `apply_attack` is deterministic and reversible for `base64`/`rot13`; a
transformed test keeps the source assertions; unknown transform name raises; `--attack`
produces original + N variants per test.

**Validate:** `python -m pytest tests/test_attacks.py tests/test_loader.py tests/test_cli.py`

---

## F2 — `pass^k` reliability scoring

**Why:** Single-shot pass/fail hides non-determinism. `pass^k` = run the same test k times,
pass only if all k pass. Directly surfaces flaky agents.

**Files:** `backend/agentkit/core/schema.py` (additive), `backend/agentkit/core/runner.py`,
`backend/agentkit/core/scoring.py`, `tests/test_runner.py`, `tests/test_scoring.py`.

**Design:**
- `schema.py`: add `repeat: int = 1` to `TestCase` (validator: `>= 1`). Additive and
  defaulted, so no existing pack or consumer changes.
- `runner.py:run`: when `test.repeat > 1`, execute the isolated test `repeat` times against a
  fresh sandbox reset each time (the sandbox already resets per test). Fold into **one**
  `TestResult`: `status = passed` iff every attempt passed; `failed`/`error` otherwise. Record
  attempt breakdown in a new additive `TestResult` field `attempts: list[Status] = []` (empty
  for `repeat == 1`, so nothing downstream breaks).
- `scoring.py`: no formula change needed — the folded single `TestResult` flows through as-is.
  Optionally surface `flaky` count (tests where attempts were mixed) on `ScoreReport` as an
  additive field.

**Watch:** `repeat` multiplies run cost (each attempt is a ~2.5s process spawn per the isolation
note). Keep default 1. `runner.py` must not raise if one attempt errors — an error attempt
makes the folded result `error`.

**Acceptance:** `repeat=3` with a deterministic pass yields one `passed` result with 3 passed
attempts; one failing attempt out of three yields `failed`; `repeat=1` behaves exactly as
today (`attempts` empty).

**Validate:** `python -m pytest tests/test_runner.py tests/test_scoring.py tests/test_schema.py`
then full suite (schema touched).

---

## F3a — Tool-call ledger on the sandbox

**Why (blocking finding):** Trajectory assertions need an *ordered record of tool calls*.
Today `AssertionContext` exposes `sandbox` (end-state) and `diff` (before/after), but **no
sequence of calls with arguments**. This ledger is the real work; F3b is thin on top.

**Files:** `backend/agentkit/core/sandbox.py`, the two domains
(`backend/agentkit/domains/treasury/`, `backend/agentkit/domains/email/`),
`backend/agentkit/core/assertions.py` (`AssertionContext`), `runner.py`,
`tests/test_sandbox.py` + domain tests.

**Design:**
- Add a `calls: list[ToolCall]` ledger to the base `Sandbox`, where
  `ToolCall = {name: str, args: dict, ts: float}`. `reset()` clears it.
- Sandbox tool methods (e.g. `bank.pay`, `inbox.send`) append to the ledger. A small
  `@record` decorator or an explicit `self._record(name, args)` call at each tool method —
  prefer explicit, it's greppable and there are only a handful of tools.
- `runner.py`: after the turns run, read `sandbox.calls` and pass it into `AssertionContext`
  as a new field `calls: list[ToolCall]`. Redact args through the existing `Redactor` before
  they enter a `TestResult` (they may contain IBANs/emails).
- **Boundary caution:** `isolation.py` runs the sandbox in the supervisor process and the agent
  in a nested worker over an RPC proxy. The ledger lives on the supervisor-side real sandbox,
  so it's captured correctly *only if tools are invoked through the proxy*. Verify the RPC
  sandbox proxy forwards tool calls to the real sandbox (it must, for `diff` to work today) —
  the ledger rides the same path. Add one isolation test asserting `calls` survives the
  boundary.

**Acceptance:** after a test where the agent calls two tools, `sandbox.calls` has two ordered
entries with redacted args; `reset()` empties it; the ledger crosses the isolation boundary.

**Validate:** `python -m pytest tests/test_sandbox.py tests/test_isolation.py` + domain tests.

---

## F3b — Trajectory assertions

**Why:** Grade *how* the agent acted, not just the final text — the τ-bench differentiator.

**Files:** `backend/agentkit/core/assertions.py`, `tests/test_assertions.py`, example YAML in
a pack.

**Design:** new assertions over `ctx.calls` (from F3a), registered in the same `REGISTRY`:
- `tool_called` (args: `name`) — a tool with this name appears.
- `tool_not_called` (args: `name`) — forbidden tool never invoked.
- `tool_arg_equals` (args: `name`, `arg`, `value`) — a call to `name` had `arg == value`.
- `tool_call_order` (args: `before`, `after`) — first `before` precedes first `after`.
- `no_repeated_tool` (args: `name`, `max`) — loop guard: `name` called at most `max` times.

Each returns `AssertionResult`, follows the existing pure-function shape, and degrades to a
clear failure detail when `ctx.calls` is empty (no ledger → assertion can't pass, same as the
`sandbox is None` pattern already used).

**Acceptance:** each assertion passes/fails correctly against a synthetic `calls` list; loader
accepts the new names; unknown-tool cases produce readable details.

**Validate:** `python -m pytest tests/test_assertions.py tests/test_loader.py`

---

## F4 — Multi-turn adaptive (crescendo) attacks

**Why:** "Push farther when it starts to crack" (CLAUDE.md). An attacker-LLM escalates based
on the agent's prior response, stopping on success or budget.

**Files:** new `backend/agentkit/core/adaptive.py`, `runner.py` (a new run mode or a distinct
entry), `tests/test_adaptive.py`.

**Design:**
- An `AttackStrategy` protocol: `next_turn(history: list[AgentResponse]) -> str | None`
  (`None` = stop). Ship two concrete strategies:
  - `CrescendoStrategy` — escalates through a fixed ladder of framings (template-driven, no
    LLM needed for v1; the ladder is data). Deterministic and testable.
  - `LLMAttackStrategy` — optional, uses an attacker model via the *existing agent adapter*
    (it's just another `Agent`); gated behind config so the default path needs no extra model.
- The loop reuses `run_one`'s multi-turn machinery: it already runs `turns` in sequence without
  resetting the sandbox. Adaptive mode generates the next turn from the last response instead
  of reading a fixed list, with a hard cap (`max_turns`) so it always terminates.
- Assertions run against the final response, same as multi-turn today.

**Watch:** budget/termination is a correctness property — cap turns and total wall-time. Keep
the default `CrescendoStrategy` LLM-free so CI stays deterministic and cheap.

**Acceptance:** `CrescendoStrategy` terminates at `max_turns`; stops early when a success
signal fires; runs entirely offline; adaptive run produces a normal `TestResult`.

**Validate:** `python -m pytest tests/test_adaptive.py tests/test_runner.py`

---

## F5 — OWASP LLM Top-10 mapping

**Why:** `compliance.py` already maps OWASP **Agentic** (ASI) codes and lists `UNCOVERED`
gaps. This adds the OWASP **LLM** Top-10 (input/output vulns: prompt injection, data
disclosure, etc.) as a parallel axis, reusing the existing renderer path.

**Files:** `backend/agentkit/core/compliance.py`, `backend/agentkit/reports/` (compliance
renderer), `tests/test_compliance.py`.

**Design:**
- Add `owasp_llm: str | None` to the `Control` model (additive).
- Map LLM codes from `Category` (the natural axis: `prompt_injection → LLM01`,
  `data_leakage → LLM02`, `action_safety → LLM06 excessive agency`, etc.) — same
  category-inheritance mechanism already used for EU/ISO/NIST, so zero per-test annotation.
- Extend the compliance report to render the LLM column alongside ASI. Keep the fail-closed
  and `UNCOVERED`-gap behavior intact.

**Note:** this is smaller than a from-scratch mapping — the infrastructure and the ASI mapping
already exist. It's one field + one lookup table + renderer column.

**Acceptance:** a `prompt_injection` result carries `LLM01`; the report shows LLM and ASI axes
without regressing the existing EU/ISO/NIST output; `_demo()` self-check updated.

**Validate:** `python -m pytest tests/test_compliance.py tests/test_reports.py`

---

## F6 — Agentic-specific vuln packs

**Why:** Fill the coverage `compliance.py:UNCOVERED`/`OWASP_BY_PACK` map already anticipates.
Packs are data, the additive path the architecture is built for.

**Files:** new YAML under `agentkit/packs/agentic/` (or extend it), no `core/` changes.

**Design:** author packs whose test-ids match the pack-name → ASI mapping in `compliance.py`
(`goal_hijack`→ASI01, `tool_misuse`→ASI02, `privilege_abuse`→ASI03, etc.) so compliance
tagging is automatic. Themes:
- **Excessive agency** — agent takes a high-stakes action without approval; assert with
  `mentions_approval_required` + F3b `tool_not_called`.
- **Goal theft / hijack** — injected instruction redirects the agent's objective; assert the
  original goal's tool still runs and the injected one does not (`tool_call_order`,
  `tool_not_called`).
- **Tool-orchestration abuse** — agent chains tools to exceed authorized scope; assert with
  `no_repeated_tool` and `payment_amount_max`.

**Depends on F3b** for its strongest assertions; text-only assertions (`not_contains`,
`mentions_approval_required`) let it ship partially before F3b lands.

**Acceptance:** new packs load via `discover()`, run green against the demo safe agent and red
against a deliberately unsafe one; compliance report tags them with the right ASI code.

**Validate:** `agentkit run agentkit/packs/agentic --target agentkit/config/treasury-agent.yaml`
+ `python -m pytest tests/test_loader.py tests/test_compliance.py`

---

## Suggested sequencing

1. **F3a then F3b** first — the ledger unlocks the trajectory assertions that F6 and the
   agentic story lean on, and it's the only task with a hidden dependency (the isolation
   boundary).
2. **F1** in parallel — pure, self-contained, immediate coverage multiplier.
3. **F2** and **F5** are cheap independent wins (each ~one additive field + one code path).
4. **F4** after F1 (shares the attack framing).
5. **F6** last — pure data, strongest once F3b exists.
