---
id: target-config
title: Target config reference
sidebar_position: 2
---

# Target config reference

A target config is a YAML file describing how to reach the agent, which sandbox
to give it, and how much evidence to keep.

## Full example

```yaml
id: my-agent
agent:
  type: http
  endpoint: "https://your-agent.example.com/chat"
  method: POST
  headers:
    Authorization: "Bearer ${AGENT_TOKEN}"
    X-Tenant: "acme"
  request:
    json:
      message: "{{ input }}"
      stream: false
  response:
    text_path: "$.reply"
  timeout_s: 30
sandbox: treasury
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

## Top level

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Name for this target. Appears in reports and run history. |
| `agent` | yes | How to reach the agent. See below. |
| `sandbox` | no | Sandbox name: `treasury`, `email`, or one you registered. |
| `evidence` | no | What to store and what to mask. Defaults to storing both, redacted. |

## `agent` — HTTP

```yaml
agent:
  type: http
  endpoint: "https://your-agent.example.com/chat"
```

| Field | Default | Meaning |
| --- | --- | --- |
| `type` | — | Must be `http`. |
| `endpoint` | — | Full URL. Must be `https` and publicly routable. |
| `method` | `POST` | `POST` or `GET`. |
| `headers` | `{}` | Sent with every request. Use `${VAR}` for secrets. |
| `request` | `{}` | Request body. Put `{{ input }}` where the prompt goes. |
| `response.text_path` | `$.text` | Dotted JSON path to the reply text. |
| `timeout_s` | `30` | Per-request timeout in seconds. |

Anything under `request` that `httpx` accepts is passed through: `json`,
`params`, `data`, `content`.

```yaml
# OpenAI-compatible chat endpoint
request:
  json:
    model: "my-agent"
    messages:
      - { role: "user", content: "{{ input }}" }
response:
  text_path: "$.choices[0].message.content"
```

## `agent` — callable

For an agent you can import. Much faster than HTTP and useful for local
iteration.

```yaml
agent:
  type: callable
  callable: "mypackage.agent:create_agent"
```

| Field | Meaning |
| --- | --- |
| `type` | Must be `callable`. |
| `callable` | `module.path:factory_name`. The factory returns a function taking `(input: str, sandbox)` and returning a string. |

## `evidence`

| Field | Default | Meaning |
| --- | --- | --- |
| `store_request` | `true` | Keep the redacted request. |
| `store_response` | `true` | Keep the redacted response. |
| `redact.use_builtins` | `true` | Apply built-in credential and PII masks. |
| `redact.literals` | `[]` | Exact strings to mask. |
| `redact.patterns` | `[]` | Named regexes to mask. Applied case-insensitively. |

See [Redaction and evidence](../concepts/redaction.md) for the built-in pattern
list.

## Environment variable interpolation

`${VAR}` anywhere in the config is replaced from the environment when the file
loads. If the variable is unset, loading fails with a clear error rather than
sending a literal `${VAR}` to the agent.

```yaml
headers:
  Authorization: "Bearer ${AGENT_TOKEN}"
endpoint: "${AGENT_BASE_URL}/chat"
```

Never put a literal token in the file.

## Environment variables

| Variable | Effect |
| --- | --- |
| `AGENTAUDIT_EGRESS_ALLOW_LOCAL=1` | Permit loopback and private-range endpoints. Development only. |
| `AGENTAUDIT_ATTACKER_ENDPOINT` | OpenAI-compatible endpoint for the attacker model. |
| `AGENTAUDIT_ATTACKER_MODEL` | Attacker model name. |
| `AGENTAUDIT_AUTH_MODE` | `dev` or `oidc`. Required as `oidc` for a non-loopback UI bind. |
| `AGENTAUDIT_ARTIFACTS_DIR` | Where artifact blobs are written. Defaults to `database/artifacts`. |

## Bundled example configs

| File | Use |
| --- | --- |
| `agentaudit/config/my-agent.example.yaml` | Template to copy for your own agent. |
| `agentaudit/config/treasury-agent.yaml` | Demo treasury agent, in-process. |
| `agentaudit/config/email-agent.yaml` | Demo email agent, in-process. |
| `agentaudit/config/treasury-http.yaml` | Demo treasury agent over HTTP. |
| `agentaudit/config/demo-stub-http.yaml` | Minimal HTTP stub for smoke testing. |
