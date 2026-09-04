---
id: compliance-evidence
title: Compliance evidence
sidebar_position: 6
---

# Compliance evidence

agentaudit can group a run's results by regulatory obligation, producing a
document a risk or governance reader can use.

:::warning This is technical evidence, not a determination
The compliance report shows which technical controls were exercised and what the
outcome was. It is **not** a compliance or CE determination, and it does not make
your system conformant. It is one input to a conformity assessment that a
qualified person still has to make.
:::

## Generate it

Add `--compliance` to any run:

```bash
agentaudit run core \
  --endpoint https://your-agent.example.com/chat \
  --compliance
```

Then render:

```bash
agentaudit report --run <run_id> --format compliance        # Markdown, grouped by article
agentaudit report --run <run_id> --format compliance-json   # machine-readable, for a GRC tool
```

## How the mapping works

Every test carries a `category`. Each category maps to a set of controls across
three frameworks. You do not tag tests with article numbers yourself — the
category does it.

| Category | EU AI Act | ISO 42001 | NIST AI RMF |
| --- | --- | --- | --- |
| `endpoint_contract` | Art. 13 | A.6 | MEASURE |
| `prompt_injection` | Art. 15 | A.8 | MEASURE |
| `data_leakage` | Art. 10, Art. 15 | A.7 | MAP/MEASURE |
| `instruction_following` | Art. 13 | A.6 | MEASURE |
| `action_safety` | Art. 14, Art. 15 | — | — |

Roughly: Article 10 is data governance, Article 13 is transparency, Article 14 is
human oversight, Article 15 is accuracy, robustness and cybersecurity.

## Fails closed

A run with no tests, or with every test skipped, reports `INCOMPLETE` — never
`PASS`.

This is the single most important property of the report. Absence of evidence is
not evidence of safety, and a compliance artifact that says "pass" because
nothing ran is worse than no artifact at all.

## Making the evidence defensible

A reader will ask three questions.

**What did you test?** The report lists every test, its category, and its
outcome.

**What did you not test?** If you used `--plan --max-tests N`, the plan records
which tests were ranked out and why. Include it:

```bash
agentaudit report --run <run_id> --format plan
```

**Can you reproduce it?** Every run is stored in `database/agentaudit.db` with the
redacted request, the response, the sandbox before/after diff, and the latency.
Archive the database alongside the report.

## Human oversight evidence

Article 14 is about human oversight. The tests that speak to it live in
`packs/agentic/human_oversight`: missing approval token, autonomous drift,
excessive agency. Run that subdirectory when oversight is the obligation you need
to evidence:

```bash
agentaudit run agentic/human_oversight \
  --target agentaudit/config/treasury-agent.yaml --compliance
```

## Redaction and evidence retention

Evidence is redacted before it is stored. For a high-sensitivity system you can
also decline to store the transcript at all, keeping the verdict and the sandbox
diff:

```yaml
evidence:
  store_request: false
  store_response: false
```

See [Redaction and evidence](../concepts/redaction.md).
