---
id: ci-integration
title: CI integration
sidebar_position: 5
---

# CI integration

The exit code is the whole integration story. `agentaudit run` exits non-zero when
the gate fails, so any CI system can block on it.

## Exit codes

| Code | Meaning | What CI should do |
| --- | --- | --- |
| `0` | Gate passed | Continue |
| `1` | Gate failed: below threshold, or a critical test failed | Block |
| `2` | Usage or config error | Block, and fix the pipeline |

Treat `2` differently from `1`. A `2` means agentaudit never got to test anything,
so it is a broken pipeline, not a broken agent.

## GitHub Actions

```yaml title=".github/workflows/agent-audit.yml"
name: agent audit

on: [pull_request]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: pip install -e .

      - name: Run the audit
        env:
          AGENT_TOKEN: ${{ secrets.AGENT_TOKEN }}
        run: |
          agentaudit run core \
            --target agentaudit/config/my-agent.yaml \
            --fail-under 0.85 \
            --format json > run.json

      - name: JUnit report
        if: always()
        run: |
          RUN_ID=$(python -c "import json,sys; print(json.load(open('run.json'))['run_id'])")
          agentaudit report --run "$RUN_ID" --format junit --out junit.xml

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: audit-evidence
          path: |
            junit.xml
            database/agentaudit.db
```

`--format json` on the run gives you the run id for the report step. Upload the
database as an artifact so you can inspect a failure locally afterwards.

## Post results on the pull request

The `md` format is written for PR comments:

```yaml
      - name: Comment on the PR
        if: always()
        run: |
          RUN_ID=$(python -c "import json;print(json.load(open('run.json'))['run_id'])")
          agentaudit report --run "$RUN_ID" --format md --out comment.md
          gh pr comment "${{ github.event.pull_request.number }}" --body-file comment.md
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Choosing a threshold

Do not start at `0.95`. Run once against your current agent and use the score you
get as the floor:

```bash
agentaudit run core --target my.yaml --fail-under 0.0
```

Take the reported overall score, subtract a little for noise, and set that as
`--fail-under`. The gate becomes a ratchet: it blocks regressions immediately
without requiring a rewrite first. Raise it as you fix things.

## Regression gate

An absolute threshold misses a specific regression when other tests improve. Add
a comparison against the last good run:

```bash
agentaudit compare "$BASELINE_RUN_ID" "$NEW_RUN_ID"
```

Exits `1` when a critical safety test that passed in the baseline now fails.
Store the baseline run id somewhere stable — a repository variable, or the
database committed as an artifact from the last main-branch build.

## Keeping the database small

Every run is persisted. On a busy repository the file grows.

```bash
agentaudit purge --keep-days 30      # drop runs older than 30 days
agentaudit purge --keep-last 100     # keep only the newest 100 runs
```

## Keeping CI deterministic

Two features reach out to a model and are off unless configured:

- `adaptive.refine` on a test needs `AGENTAUDIT_ATTACKER_ENDPOINT` and
  `AGENTAUDIT_ATTACKER_MODEL`. Without them, the test falls back to a scripted
  ladder and stays deterministic.
- `agentaudit run --external` spawns promptfoo or garak, which dial your endpoint
  themselves and are not bound by the pinned address. It is opt-in for exactly
  that reason.

Leave both off in CI unless you have decided otherwise on purpose.
