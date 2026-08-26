# PRD-001: MCP Security Pack

**Type:** Feature · **Priority:** 1 (highest)

## Problem

Model Context Protocol (MCP) servers are becoming the dominant tool-integration
surface for agents, and they introduce attack classes that single-prompt
probes cannot see:

- **Tool-description poisoning** — malicious instructions embedded in a tool's
  description or schema that hijack the agent when the tool list is loaded.
- **Server impersonation / rug pulls** — a trusted server silently changes
  behavior between sessions.
- **Unsafe tool composition** — chained calls that escalate privilege or
  exfiltrate data across tool hops.
- **Excessive agency** — the agent invokes tools it should never combine.

agentaudit already tests exactly this shape of failure — *actions*, not reply
text — but only against its two built-in verticals (treasury, email) via
hand-written `Sandbox` subclasses. There is no way to point agentaudit at a
live MCP server and probe it.

## Evidence

- Microsoft security research (Jun 2026): poisoned tool descriptions alone can
  make agents leak data with no rule visibly broken.
- OWASP LLM06 (Excessive Agency) and the OWASP Agentic (ASI) taxonomy map
  directly onto these failure modes; `core/compliance.py` currently declares
  several ASI codes uncoverable.
- Practitioner discussions (r/AI_Agents, AppSec Santa 2026 red-teaming survey)
  flag MCP scanning as the biggest unmet need in agent security tooling;
  dedicated scanners (e.g., MCP Scan) exist but none integrate results into a
  CI-gateable regression harness with side-effect evidence.

## Goals

1. A new target adapter type: **MCPServerAgent** — connects to an MCP server
   (stdio and streamable HTTP transports), lists tools/resources, and drives
   the agent under test against them.
2. A reusable **`McpToolboxSandbox`** that records tool invocations as
   side-effect events so existing assertions (`tool_called`,
   `tool_not_called`, `tool_arg_equals`, `no_repeated_tool`, …) work
   unchanged.
3. A shipped pack `agentaudit/packs/mcp/` covering:
   - poisoned tool description → does the agent obey the injected instruction?
   - description-injection encoding variants (reuse `core/attacks.py` transforms)
   - rug-pull simulation (tool behavior mutates mid-session)
   - cross-tool exfiltration (data from resource A appears in call to tool B)
   - excessive-agency chains (multi-tool combinations that should require approval)
4. Compliance mapping for newly coverable ASI codes; remove them from
   `UNCOVERED` (`core/compliance.py`) once probes ship.

## Non-goals

- Building an MCP client SDK from scratch — use the official `mcp` Python SDK.
- Static analysis of server code (that is Agentic Radar's job).
- Scanning third-party MCP registries.

## User stories

- As an AI engineer, I register my MCP server URL/command in a target YAML and
  run `agentaudit run agentaudit/packs/mcp --target my-server.yaml`, getting
  pass/fail per poisoning scenario with evidence of which tools fired.
- As a security reviewer, I see every failed scenario mapped to OWASP ASI
  codes in the compliance report without extra configuration.
- As a pack author, I can add a new MCP scenario by writing YAML only, because
  the sandbox emits generic tool-event facts.

## Requirements

1. `MCPServerAgent` in `backend/agentaudit/domains/mcp/agent.py`, registered
   via the existing `build_agent` factory path (`core/agent.py:259`).
2. Sandbox events must include tool name, arguments hash, response hash, and
   timestamp — enough for assertions, never raw secrets.
3. New scenarios are pure YAML cases validated by `core/loader.py` at
   discovery time; zero new assertion code required for the v1 pack.
4. All network transport goes through `core/egress.py` policy validation
   (httpx stays confined to `core/agent.py`; enforced by
   `tests/test_security_p0.py`).
5. Tests mirror modules per repo convention:
   `tests/test_mcp_agent.py`, `tests/test_mcp_sandbox.py`.

## Success metrics

- ≥ 8 shipped MCP scenarios, all deterministic offline (fake MCP server fixture).
- Unsafe fixture agent fails ≥ 60% of the pack (proves detection power), safe
  agent passes 100%.
- At least 2 previously-`UNCOVERED` ASI codes become reportable.

## Open questions

- stdio transport on Windows Job Objects (`core/isolation.py`) — confirm child
  process cleanup semantics before v1.
- Should rug-pull simulation be opt-in only (it requires mutating server state)?
