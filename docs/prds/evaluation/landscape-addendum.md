# Task 1 addendum — landscape gaps (researched 2026-08-27)

Extends [`landscape.md`](landscape.md) (2026-08-26). That survey covered the
eval/red-team frameworks well. It missed two whole product categories and one direct
positional competitor. This file adds only what was missing; nothing here restates it.

## Category A — MCP/skill supply-chain scanners (entirely absent from landscape.md)

This category did not exist in the earlier survey at all, and it is the category that
sits closest to AgentAudit's newly-shipped `packs/mcp`.

| Tool | What it tests | Maturity | Key strength | Key gap |
|---|---|---|---|---|
| **Snyk `agent-scan`** | Static scan of MCP servers, tool descriptions, skills, agent configs; 15+ risk classes (prompt injection, tool poisoning, tool shadowing, toxic flows, destructive capability, secrets). Auto-discovers Claude Code/Desktop, Cursor, Gemini CLI, Windsurf configs | ~3.0k stars, 728 commits, active, vendor-backed | Zero-config discovery of what is *installed*; supply-chain framing | **Static** — reads tool metadata, never observes agent behavior. Cannot tell you whether *your* agent obeys a poisoned description |
| **Invariant `mcp-scan`** | Tool poisoning, rug pulls, cross-origin escalation, prompt injection in MCP configs | Established; the de-facto MCP scanner | First mover; named the tool-poisoning attack class | Config/metadata layer only; no behavioral assertion |
| **`mcp-scanner`** (eSentire Labs / Cisco lineage) | Keyword + semantic + LLM-judged detection of variable/tool poisoning, rug pulls, server impersonation; peer-reviewed (ACM/IEEE EnCyCriS 2026) | Research-backed, OSS | Academic validation; layered detection | LLM-judged layer reintroduces judge variance; still static |
| **MCP-Shield** | Hidden instructions in tool descriptions, tool shadowing, behavior modification, exfiltration channels | Smaller OSS | Focused on description-level attacks | Static; narrow |

**Why this matters for AgentAudit.** These tools answer *"is this MCP server malicious?"*
AgentAudit's `mcp` pack answers a strictly different and unserved question: *"does my
agent get exploited when a tool description is poisoned?"* — verified by a fake toolbox
that records whether `send_to_endpoint` actually fired
(`backend/agentaudit/domains/mcp/sandbox.py`). **No scanner in this category asserts on
runtime side effects.** That is a real, defensible, currently-uncontested wedge — and
AgentAudit ships exactly **one** test in it (`poisoned_description.yaml`).

Context on demand: Snyk's ToxicSkills study found prompt injection in 36% of ~4,000
agent skills, 534 with critical issues, and an active malware campaign via ClawHub with
"no code signing, no security review, no sandbox by default."

## Category B — direct positional competitor (missed)

| Tool | What it tests | Maturity | Key strength | Key gap |
|---|---|---|---|---|
| **ProofAgent Harness** | Adversarial multi-turn behavioral eval (183 traps / 11 families), context-engineering quality, compliance across **25 frameworks** (EU AI Act, NIST, SOC 2, GDPR…), governance release gates; 6 scored metrics; "code-proven checks where possible before consulting juror LLMs"; deterministic seeds; local-first | ~27 stars, 91 commits — **not a market threat**, but the closest positional twin found | Occupies AgentAudit's exact pitch: adversarial + CI + compliance + evidence-backed + local | No sandbox/fake world — grades conversation, planted canary values, and artifacts. Juror LLMs in the loop |

**Why this matters.** Two independent teams converged on "adversarial multi-turn + CI gate
+ compliance evidence, run locally." That validates the category and **weakens the
compliance differentiator specifically**: ProofAgent maps 25 frameworks to AgentAudit's 3.
The durable difference is still the fake world, not the compliance report.

## Correction to landscape.md's framing

`landscape.md` finding #1 says the "actions vs words" moat is narrowing because promptfoo
needs OTel spans and RAMPART needs an adapter. That holds, and the addendum sharpens it:
across **both** new categories surveyed here — four MCP scanners and ProofAgent — **not one
asserts on world state in a pre-built fake environment.** The moat is narrower than the
README implies but real, and it is narrowest exactly where AgentAudit is thinnest
(breadth), and widest where it has almost no content (MCP behavioral testing).

## One competitive weakness AgentAudit already solves but does not market

promptfoo is critiqued for having "no persistent dashboard, no shared experiment history,
and no way for a PM to stay in the loop on the latest eval run"
([Braintrust](https://www.braintrust.dev/articles/best-promptfoo-alternatives-2026)).
AgentAudit ships a SQLite-backed, org-scoped, OIDC-capable dashboard with per-test
history across runs. That is a genuine advantage over the market leader that appears
nowhere in the README's comparison table.

## Sources

- [snyk/agent-scan](https://github.com/snyk/agent-scan) ·
  [Snyk: detecting tool poisoning](https://labs.snyk.io/resources/detect-tool-poisoning-mcp-server-security/) ·
  [Snyk ToxicSkills study](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/)
- [Invariant Labs: MCP tool poisoning notification](https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks)
- [MCP-Scanner (ACM/IEEE EnCyCriS 2026)](https://dl.acm.org/doi/10.1145/3786160.3788471) ·
  [eSentire-Labs/mcp-scanner](https://github.com/eSentire-Labs/mcp-scanner)
- [MCP Security in 2026: tool poisoning, OWASP MCP Top 10](https://mcpplaygroundonline.com/blog/mcp-security-tool-poisoning-owasp-top-10-mcp-scan)
- [ProofAgent-ai/proofagent-harness](https://github.com/ProofAgent-ai/proofagent-harness)
- [CSA: SKILL.md agent context poisoning](https://labs.cloudsecurityalliance.org/research/csa-research-note-skill-md-agent-context-poisoning-20260506/) ·
  [Orca: skill marketplace supply chain](https://orca.security/resources/blog/ai-agent-skill-supply-chain-security/)
- [Braintrust: promptfoo alternatives](https://www.braintrust.dev/articles/best-promptfoo-alternatives-2026)
