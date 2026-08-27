# Task 2 — AgentAudit assessment against the landscape

Assessment date 2026-08-26, against commit `80c53e4` on `fix/audit-findings-scoring-spa`.
Behavioral claims below were verified by running the tool locally (bare core pack vs a
sandbox-less stub agent; treasury pack vs the safe demo agent; agentic pack vs the
overtrusting demo agent), not just by reading code.

## 1. Problem fit

**Where it genuinely wins.** The sandbox side-effect model is real and works: the agentic
pack against the deliberately overtrusting agent produced 7 critical failures,
`Gate: BLOCK`, exit code 1 — with evidence from a fake bank's payment ledger, not from
reading the agent's apology. That is exactly the failure mode practitioners describe as
missed by text-graders ("a safe-looking final answer is not enough if the agent already
used the wrong tool" — promptfoo's own agent guide, echoed in community discussion). No
tool in the landscape ships pre-built fake *worlds*; RAMPART needs you to write an adapter,
promptfoo needs OTel spans. The deterministic assertion registry (19 built-ins) also means
zero LLM-judge variance in gating — a direct answer to the loudest complaint about eval
tooling (see pain-points.md #2). The compliance report (EU AI Act / ISO 42001 / NIST /
OWASP ASI mapping, with an explicit UNCOVERED list) remains rare: only promptfoo and DeepTeam
approach it among OSS.

**Where it loses today.**
- **Breadth**: 20 core + ~28 domain/agentic tests vs garak's 120+ probes and promptfoo's
  50+ plugins × strategies. The README concedes this; since then garak added agent-breaker
  probes and DeepTeam ships OWASP Agentic mapping, so the gap widened.
- **Single-run gates**: every gate is one sample of a nondeterministic distribution.
  RAMPART ships trial policies natively; agentaudit has `repeat`/pass^k folding in the
  runner but no default, no threshold policy, no docs steering users to it (→ PRD-004 in
  this repo already targets this; still unimplemented).
- **The quickstart lies by accident**: bare `agentaudit run core` reports three jailbreak
  tests as FAILED with detail "sandbox has no bank" on any sandbox-less target — harness
  misconfiguration rendered as security findings against the agent. Verified directly:
  an echo-stub agent scored 85% pass with three false high-risk failures. A first-time user
  cannot tell their agent wasn't actually attacked meaningfully. (Fixed on branch
  `fix/core-skip-without-sandbox`, PRD-006.)

## 2. User path clarity (first-time walkthrough)

1. **Setup** — clone, `pip install -e .`, one command to first run. Good; PATH fallback is
   documented. Frictionless compared with PyRIT-class SDKs.
2. **Run a test** — `agentaudit run core --endpoint ...` assumes `POST {"input"}` /
   `{"text"}`; deviations need a YAML config, documented with `${VAR}` secret handling. OK —
   but see the fail-closed bug above: the default path produced misleading results.
3. **Read results** — terminal table + persisted run + `report --format`. Two doc bugs here:
   the sample output showed a `jailbreak` category that cannot exist (schema has no such
   enum value) and wrong row counts (fixed on `fix/readme-quickstart-output`). The SKIP
   column was previously never explained; it now will be.
4. **Act on findings** — this is the weakest step for a new user. `compare` needs two run
   IDs and isn't referenced from the quickstart; there's no "what do I do when test X fails"
   guidance per finding; the dashboard requires discovering `agentaudit ui` on your own.
   Findings carry assertion detail but no remediation hint.

## 3. Feature depth vs breadth

**Currently quantity-leaning at the edges, quality-leaning at the core.** The core loop
(run → assert-on-side-effects → score → gate → compare → report) is done well: fails-closed
scoring, redaction ordering enforced by tests, isolation supervisor, security-P0 suite.
But the surface advertised around it is wide for an MVP: adaptive ladders, attacker/judge
models, evolve review queue, discovery/profiling/planner, promptfoo/garak adapters
(`--external`), OIDC dashboard with ~33 API routes, compliance reports, Alembic migrations.
Several of these are opt-in shells over thin foundations (e.g., adapters execute external
tools but planner integration is cost-ranked selection; evolve needs external model env
vars). For a pre-traction MVP this is the wrong trade at the margin: the roadmap itself
("attack iteratively") is unbuilt while its supporting cast is. Depth on the differentiator
(sandboxes, assertions, verticals) beats one more half-integrated subsystem.

## 4. Verdict

**Partial yes — it solves the *hard half* of my main problem and none of the easy half.**

- Solves: "did the agent do the unsafe thing to its tools?" with CI-gateable, judge-free,
  side-effect evidence — better than any tool I found for the two shipped verticals, and
  the model the field is converging toward (RAMPART's evaluators, promptfoo's trajectory
  work validate it).
- Does not solve: breadth of attack coverage (still far behind garak/promptfoo/DeepTeam),
  trustworthy single-run gating under nondeterminism, cheap onboarding of a third domain
  (hand-written `Sandbox` subclass), and a first-run experience that currently miscalibrates
  trust via false failures. What it depends on: if your agents live in a payments/email-like
  shape and you can invest in a sandbox, it's usable now; if you need broad probe coverage
  or multi-domain coverage out of the box, promptfoo (+garak) remains the rational default
  today.
