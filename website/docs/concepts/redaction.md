---
id: redaction
title: Redaction and evidence
sidebar_position: 5
---

# Redaction and evidence

agentaudit stores what the agent was sent and what it replied, so you can look at
a failure and understand it. That evidence can contain secrets. Redaction is
therefore on by default and is not optional.

## Where redaction runs

It runs twice, on purpose:

1. In the **runner**, before a test result object is even built.
2. Again in the **store**, when the run is saved.

The second pass is defence in depth. Nothing downstream of the runner — scoring,
reports, the dashboard, the compliance renderer — ever sees an unredacted value.

## What is masked by default

Credentials first, then PII, so a bearer token is masked whole instead of having
its tail eaten by a numeric pattern.

| Pattern | Matches |
| --- | --- |
| `api_key` | `sk-`-prefixed keys |
| `bearer` | `Bearer` and `Basic` authorization values |
| `email` | Email addresses |
| `iban` | IBAN account numbers |
| `card` | 13 to 16 digit card numbers |
| `account` | 8 to 17 digit account numbers |
| `phone` | Phone numbers |

## Evidence policy

Redaction controls *what is masked*. The evidence policy controls *whether
anything is stored at all*. They are separate decisions.

```yaml
evidence:
  store_request: true
  store_response: true
  redact:
    use_builtins: true
    literals:
      - "ACME-INTERNAL-CODENAME"
    patterns:
      - name: employee_id
        regex: "EMP-[0-9]{6}"
```

| Field | Default | Meaning |
| --- | --- | --- |
| `store_request` | `true` | Keep the redacted request in evidence. |
| `store_response` | `true` | Keep the redacted response in evidence. |
| `redact.use_builtins` | `true` | Apply the built-in credential and PII masks. |
| `redact.literals` | `[]` | Exact strings to mask. Use for project-specific secrets. |
| `redact.patterns` | `[]` | Named regexes to mask. Case-insensitive. |

For a high-sensitivity environment, set both `store_request` and
`store_response` to `false`. You keep the pass/fail verdict and the sandbox diff,
and lose the transcript.

## Secrets in config files

Never write a literal token into a target config. Use `${VAR}`, which is
interpolated from the environment when the config loads:

```yaml
headers:
  Authorization: "Bearer ${AGENT_TOKEN}"
```

If the variable is unset, loading fails with a clear error rather than sending
the literal string `${AGENT_TOKEN}` to your agent.

## External tool reports

`core/adapters.py` normalizes promptfoo and garak reports into agentaudit's
schema. That path does not go through the runner, so it applies redaction and the
evidence policy itself. The rule holds everywhere: nothing is persisted raw.
