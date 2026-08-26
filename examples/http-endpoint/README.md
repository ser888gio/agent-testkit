# Zero-config HTTP endpoint quickstart

Point agentaudit at a running agent URL and run the domain-neutral `core` pack.
No sandbox needed — `core` asserts on what the agent *said*.

## Files

- `target.yaml` — target config modeled on
  [`agentaudit/config/my-agent.example.yaml`](../../agentaudit/config/my-agent.example.yaml).
  Edit `endpoint` to your agent's URL; `${AGENT_TOKEN}` is read from the
  environment at load time, so no secret lands in the file.

## Run it

```bash
export AGENT_TOKEN=...            # only if your agent needs auth
agentaudit run agentaudit/packs/core --target examples/http-endpoint/target.yaml
```

If your agent speaks the default shape — `POST {"input": "..."}` returning
`{"text": "..."}` over https — you can skip the config entirely:

```bash
agentaudit run core --endpoint https://your-agent.example.com/chat
```

Expected output: a per-category pass/fail table ending in a gate line. The exit
code is the CI gate: non-zero when the run fails its threshold or a critical
safety test fails.

Endpoints must be `https` and publicly routable; loopback/private addresses are
rejected by the egress policy unless the worker sets
`AGENTAUDIT_EGRESS_ALLOW_LOCAL=1`.

Next: every run is stored, so `agentaudit report --run <run_id> --format md` and
`agentaudit ui` work immediately after this command. See
[`docs/demo.md`](../docs/demo.md) for the full walkthrough.
