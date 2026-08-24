---
id: connect-your-agent
title: Connect your agent
sidebar_position: 1
---

# Connect your agent

`--endpoint` covers the simplest case. Anything else needs a target config.

## The simple case

```bash
agentaudit run core --endpoint https://your-agent.example.com/chat
```

This assumes a `POST` with body `{"input": "..."}` returning `{"text": "..."}`.
No auth headers.

## Write a target config

For auth headers, a different request body, or a nested reply field, copy the
example config and edit it:

```bash
cp agentaudit/config/my-agent.example.yaml agentaudit/config/my-agent.yaml
```

```yaml
id: my-agent
agent:
  type: http
  endpoint: "https://your-agent.example.com/chat"
  method: POST
  headers:
    Authorization: "Bearer ${AGENT_TOKEN}"
  request:
    json:
      message: "{{ input }}"
  response:
    text_path: "$.reply"
  timeout_s: 30
```

Then run:

```bash
export AGENT_TOKEN=...
agentaudit run core --target agentaudit/config/my-agent.yaml
```

## The three knobs

**`request`** is your request body, with `{{ input }}` wherever the test prompt
goes. Anything `httpx` accepts is passed through: `json`, `params`, `data`,
`content`.

```yaml
request:
  json:
    messages:
      - { role: "user", content: "{{ input }}" }
    stream: false
```

**`response.text_path`** is the dotted JSON path to the reply.

```yaml
response:
  text_path: "$.choices[0].message.content"
```

**`${VAR}`** interpolates environment variables when the config loads, so tokens
never live in the file. An unset variable is a load error, not a silent pass-through.

## Testing an in-process agent

For a Python agent you can import, skip HTTP entirely. This is much faster and is
what the repository's own tests use.

```yaml
id: my-agent-local
agent:
  type: callable
  callable: "mypackage.agent:create_agent"
```

The callable must return a function taking `(input: str, sandbox)` and returning
a string.

## Adding a sandbox

To run domain packs that assert on side effects, name a sandbox:

```yaml
id: my-payments-agent
agent:
  type: http
  endpoint: "https://your-agent.example.com/chat"
sandbox: treasury
```

Built-in names are `treasury` and `email`. For your own, see
[Add a sandbox](./add-a-sandbox.md).

:::note
A sandbox only observes side effects if the agent actually calls into it. For an
HTTP agent, that means your agent's tools must be pointed at the sandbox during
the test run. An HTTP agent talking to your real production bank will produce a
sandbox diff that is empty and a test that passes for the wrong reason.
:::

## Endpoint restrictions

Endpoints must be `https` and publicly routable. Loopback and private IP ranges
are rejected by the egress policy. To test locally:

```bash
export AGENTAUDIT_EGRESS_ALLOW_LOCAL=1
```

Only do this on a development machine.

## Check it works before running a pack

```bash
agentaudit run core/endpoint_contract --target agentaudit/config/my-agent.yaml
```

Three quick contract tests. If those fail, the connection is wrong, not the
agent.
