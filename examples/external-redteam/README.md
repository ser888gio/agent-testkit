# External red-team tools: promptfoo / garak via `--external`

agentaudit can orchestrate [promptfoo](https://promptfoo.dev) or
[garak](https://github.com/NVIDIA/garak) against your endpoint and normalize
their findings into agentaudit's result schema, store, and reports. The tools
are **not** dependencies — install whichever you want and agentaudit finds the
binary on `PATH`.

## Run it

External execution runs through the planner, so pass both flags together:

```bash
npm install -g promptfoo            # or: pip install garak
agentaudit run core --endpoint https://your-agent.example.com/chat --plan --external
```

What happens:

1. `--plan` probes your endpoint with two trivial requests, builds a risk
   profile, and ranks agentaudit's own tests plus the external tools' catalogs
   (promptfoo plugins, garak probe modules).
2. `--external` additionally spawns the external tool(s) the plan selected,
   pointed at your endpoint, and merges their normalized results into the run.

Expected output: the plan table first (selected tests with sources), then the
usual category table where promptfoo/garak rows appear alongside agentaudit's
own results. Tests belonging to external tools that were selected but not
executed are listed under `note: ... not executed by this run`.

## Notes

- The endpoint must be reachable by the external tool itself: spawned tools dial
  your URL directly and do not inherit agentaudit's egress-pinned address.
- If the binary is missing, the selection comes back as an explicit `error`
  result ("... is not installed on this runner") — never as a silent pass.
- External severities are re-mapped onto agentaudit's own risk ladder; anything
  that can move money, run code, or reach another system lands at high risk.
- To preview the plan without executing anything:
  `agentaudit plan core --endpoint https://your-agent.example.com/chat`.
