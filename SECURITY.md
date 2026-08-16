# Security Policy

## Reporting a vulnerability

Please do not open a public GitHub issue for security vulnerabilities.

Instead, use [GitHub's private vulnerability reporting](https://github.com/ser888gio/agent-testkit/security/advisories/new)
for this repository. Include:

- A description of the vulnerability and its impact.
- Steps to reproduce (a minimal repro is ideal).
- Affected version/commit.

We'll acknowledge reports and follow up as we assess and fix the issue.

## Scope note

`agentkit` is a testing tool that runs AI agents against fake sandboxes and, in the HTTP
mode, calls out to endpoints you configure. It is not itself an agent, does not execute
model-generated code, and does not hold real credentials. Redaction runs by default before
any evidence is persisted (`backend/agentkit/core/redaction.py`) — see
[`docs/architecture.md`](docs/architecture.md) for the trust model.
