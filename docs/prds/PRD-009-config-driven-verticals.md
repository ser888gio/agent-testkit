# PRD-009 — Config-driven domain verticals (sandbox toolkits, not subclasses)

**Type:** Feature · **Status:** Proposed

## Problem
Side-effect testing only exists for domains someone hand-built: adding a vertical means
writing a `Sandbox` subclass in Python (README Limits says so explicitly). Field reports put
integration realism — not scoring — at the center of agent-eval difficulty ("runnable ≠
evaluable"; adapter realism was the bottleneck across 19 real agents,
[pragmatic-engineer](https://pragmatic-engineer.hashnode.dev/why-agent-validation-needs-release-discipline-not-better-demos)),
and environment-state grading is the practitioner-endorsed ideal ("the environment is
evidence", [saumilsrivastava.ai](https://www.saumilsrivastava.ai/blog/agent-evaluation-is-a-distributed-systems-problem)).
AgentAudit owns the right mechanism but prices new-domain adoption at "write Python against
an internal API" — the single biggest adoption blocker identified in Task 2 §4.

## Proposed solution
A declarative sandbox toolkit: define fake resources (ledger/table, mailbox/outbox,
key-value store, generic HTTP mock), events, and setup keys in YAML; assertions
(`resource_not_created`, `no_message_to`, `state_unchanged`) generated generically from the
declaration. Ship one worked example vertical (e.g. support-ticket refund agent) built
entirely in YAML to prove zero-code extensibility. Python subclassing remains the escape
hatch, not the entry fee.

## Success criteria
- Third vertical defined end-to-end in YAML only: sandbox declaration + 5+ tests + demo unsafe agent.
- Generic assertion registry extended without touching treasury/email code; full suite green.
- New-vertical time-to-first-side-effect-test drops from "hours of API study" to "<30 min from docs".

## Priority & effort
P1 — converts the differentiator from two demo islands into a platform
· Effort: L

## Open questions
- Which resource archetypes cover 80% of verticals? (ledger/mailbox/kv/http-mock is a guess.)
- How do declarative sandboxes interact with the isolation supervisor's RPC boundary?
- Does planner profiling need new capability signals for generic domains?
