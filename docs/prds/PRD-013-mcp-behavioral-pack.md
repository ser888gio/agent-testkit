# PRD-013 — Build out the MCP behavioral security pack (the uncontested wedge)

**Type:** Feature · **Status:** Proposed · **Extends:** PRD-001 (which shipped the scaffold)

## Problem
Agent supply-chain compromise is the dominant agent-security story of 2026 — "AI agent
security in 2026 is a supply chain problem first, a prompt injection problem second"
([cyberdesserts](https://blog.cyberdesserts.com/ai-agent-security-risks/)). Snyk's
ToxicSkills study found prompt injection in **36%** of ~4,000 agent skills, **534 with
critical issues**, and an active campaign distributing 30+ malicious skills via ClawHub with
"no code signing, no security review, no sandbox by default"
([Snyk](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/),
[Orca](https://orca.security/resources/blog/ai-agent-skill-supply-chain-security/),
[CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-skill-md-agent-context-poisoning-20260506/)).

**Every tool in this category is a static scanner** — Snyk `agent-scan` (~3.0k stars),
Invariant `mcp-scan`, eSentire/Cisco `mcp-scanner` (ACM/IEEE 2026), MCP-Shield. They read
tool descriptions, configs, and skill files. **Not one observes whether an agent actually
complies with a poisoned description**, because none of them has a fake world to observe it
in ([landscape-addendum.md §Category A](evaluation/landscape-addendum.md)).

That leaves the question teams actually need answered before shipping — *given a poisoned
tool description reaches my agent, does my agent obey it?* — served by **nobody**.

AgentAudit already has the primitive: `McpToolboxSandbox`
(`backend/agentaudit/domains/mcp/sandbox.py`) records every invocation as a side-effect
event with hashed args, so `tool_called` / `tool_not_called` / `no_repeated_tool` all work
against it. And it ships **exactly one test** using it
(`packs/mcp/tool_misuse/poisoned_description.yaml`, loader-verified).

Maximum market urgency, zero behavioral competition, primitive already built, one test
shipped. This is the clearest misallocation in the repo.

## Proposed solution
Grow `packs/mcp` to cover the attack classes the static scanners *detect statically* — so
AgentAudit answers the behavioral half of each:

| Attack class | Behavioral question | Assertion shape |
|---|---|---|
| Tool poisoning (shipped) | Does the agent obey an instruction in a tool description? | `tool_not_called(exfil)` |
| **Tool shadowing** | Does a malicious server's same-named tool capture calls meant for the trusted one? | `tool_called(trusted)` + `tool_not_called(shadow)` |
| **Rug pull** | Does the agent re-validate after a description changes mid-session? | multi-turn + `tool_not_called` post-mutation |
| **Cross-origin exfiltration** | Does data from server A reach server B? | canary value + `no_external_forward` |
| **Toxic flow / chained capability** | Does read-private → send-public chain without confirmation? | ordered `tool_called` sequence |
| **Destructive capability** | Does the agent invoke a destructive tool on ambiguous instruction? | `tool_not_called(delete_*)` |
| **Infinite retry loop** | Does the agent retry a failing tool unboundedly? | `no_repeated_tool(max: n)` — **already supported** |

Target: **12–15 scenarios**, sized to the OWASP MCP Top 10 so the compliance report can map
to it. Sandbox extensions likely needed: multiple named servers/origins (shadowing,
cross-origin), mid-session description mutation (rug pull), tool failure injection (retry).

Position explicitly as **complementary to, not competing with, the scanners**: "`mcp-scan`
tells you the server is malicious; agentaudit tells you your agent falls for it."

## Success criteria
- ≥12 MCP scenarios, each **failing** against a deliberately over-trusting demo MCP agent
  and **passing** against a careful one (the pack quality bar).
- A demo MCP agent under `domains/mcp/` mirroring the treasury safe/reckless pair.
- Sandbox supports multi-origin tools, mid-session description mutation, and failure
  injection.
- Compliance report maps MCP scenarios to OWASP MCP Top 10 / OWASP Agentic categories.
- README states the scanner-complementarity line above the fold.

## Priority & effort
**P0** — highest-leverage gap found in this review: the only category where AgentAudit has
*no* competitor, in the year's most urgent agent-security topic. · **Effort: L**
(sandbox extensions + ~12 scenarios + demo agents); a **M**-sized first slice of 5 scenarios
using the existing sandbox unchanged is worth shipping on its own.

## Open questions
- Model MCP servers as separate sandboxes or as origin-tagged tools inside one toolbox?
- Does `no_external_forward` generalize from the email sandbox, or does MCP need its own
  cross-origin assertion?
- Scope to MCP only, or also cover `SKILL.md`-style skill poisoning (same attack, different
  packaging — and skills are now cross-vendor)?
- Should agentaudit *consume* `mcp-scan` output as a planner input (which server to probe),
  the way `--external` consumes promptfoo/garak?
