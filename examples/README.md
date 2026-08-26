# Examples

Three copy-paste quickstarts. Each folder has its own README with the exact
commands.

| Folder | What it shows | Needs a live agent? |
|---|---|---|
| [`http-endpoint/`](http-endpoint/) | Target YAML + `agentaudit run` against your agent's URL (core pack) | Yes |
| [`treasury-demo/`](treasury-demo/) | Side-effect testing: the unsafe fixture agent fails its own safety gate — fully offline | No |
| [`external-redteam/`](external-redteam/) | Orchestrating promptfoo/garak via `run --plan --external` | Yes |

New here and no agent to point at yet? Start with `treasury-demo`: it runs
in-process against a deliberately unsafe fixture agent and shows failing
side-effect assertions in under a minute. Then see
[`docs/demo.md`](../docs/demo.md) for the full run → dashboard → compare →
compliance-report walkthrough.

Every YAML here is validated by `tests/test_examples.py`, so these examples
cannot rot silently.
