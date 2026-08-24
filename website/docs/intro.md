---
id: intro
title: What is agentaudit?
sidebar_label: What is agentaudit?
sidebar_position: 1
slug: /
---

# What is agentaudit?

agentaudit is a black-box testing kit for AI agents. It calls your agent through
its real endpoint, checks both what the agent **said** and what it **did** to the
fake tools around it, scores the run, and writes a report you can gate CI on.

You do not share prompts, tools, or source code with it. The agent is a box with
an HTTP endpoint. agentaudit sends test inputs and watches the outcome.

## The core idea

Most agent evaluation tools grade free text: "did the reply sound safe?"
That misses the thing that actually matters for an agent with tools. An agent can
write a perfect refusal and still call the payment API.

agentaudit gives the agent a **sandbox** — a fake bank, a fake invoice store, a
fake inbox — and asserts on the state of that sandbox after the test:

> The agent said it would not pay the invoice, and the invoice store confirms it
> did not.

That is a stronger claim than any text grader can make.

## What you get

| Capability | What it means |
| --- | --- |
| Black-box adapters | Call an in-process Python function or a live HTTP endpoint. Same tests for both. |
| Sandbox side effects | Assert that a payment was not created, mail was not forwarded, a tool was not called. |
| Test packs as YAML | Tests are data, not code. Write one in six lines. |
| Redaction by default | Secrets and PII are stripped from evidence before it is stored or shown. |
| Scoring and a CI gate | Risk-weighted score, critical-failure detection, non-zero exit code when the gate fails. |
| Regression gate | Compare two runs; fail if a critical test that used to pass now fails. |
| Reports | JSON, JUnit XML, HTML, Markdown, and an EU AI Act / ISO 42001 / NIST evidence report. |
| Dashboard | A local web UI with run history, a pass/fail matrix, and per-test evidence. |

## Who it is for

Teams shipping an AI agent — a support bot, a payments assistant, an internal
copilot — who need to answer "does it still refuse to do the unsafe thing?" with
evidence, before every merge.

## Project status

agentaudit is an MVP. It ships two working demo verticals (treasury payment
approval and email phishing/exfiltration), an OWASP Agentic Top 10 attack pack,
and a compliance evidence report.

Read [Limits and roadmap](./limits.md) before you rely on it for anything
load-bearing.

## Where to go next

- [Installation](./getting-started/installation.md) — get the CLI running.
- [Quickstart](./getting-started/quickstart.md) — first run in two minutes.
- [Core concepts](./concepts/overview.md) — how tests, sandboxes, and scoring fit together.
