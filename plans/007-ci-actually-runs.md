# Plan 007: Make CI actually run on the branch the project develops on

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**:
> `git diff --stat 5959852..HEAD -- .github/workflows/ci.yml .github/workflows/security.yml`
> If either changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/006-green-the-suite.md` — **hard dependency, see below**
- **Category**: dx
- **Planned at**: commit `5959852`, 2026-08-29

## Why this matters

Both GitHub Actions workflows trigger only on `main`:

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
```

The repository's default branch is `develop`, and every pull request merged in
the recent history (#79 through #87) targets `develop`. **No CI run has ever
gated a pull request.** `gh run list` shows only Dependabot runs and the weekly
scheduled Security job — zero runs of the `CI` workflow.

The cost is not hypothetical. Plan 006 fixes two product-breaking regressions
that existing tests already caught: a `TypeError` crash in the default Markdown
report renderer, and a reference HTTP config that sends the literal string
`"input"` instead of the test prompt. Both sat red on `develop` for days. A
955-test suite, a ruff gate, a package build and a docs build are all running
against a branch nobody merges to.

Additionally the `complexity` job runs but is excluded from the `required`
aggregate gate, so its result is discarded, and `develop` has no branch
protection at all — so even a correct workflow would not block a merge.

**Why 006 must land first**: turning CI on against the current red suite would
immediately fail every pull request. Fix the suite, then close the gate.

## Current state

- `.github/workflows/ci.yml` — five jobs: `tests` (Python 3.10–3.13 matrix),
  `lint` (ruff), `complexity` (complexipy, max 26), `package` (`uv build`),
  `docs` (Docusaurus site under `website/`), plus a `required` aggregate.
- `.github/workflows/security.yml` — `dependency-audit` job (pip-audit over the
  exported lockfile), plus a weekly `schedule` trigger that *does* fire.

Excerpt (`.github/workflows/ci.yml:1-14`, verified at `5959852`):

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

`.github/workflows/security.yml:1-10` has the same `on:` block plus:

```yaml
  schedule:
    - cron: "17 6 * * 1"
  workflow_dispatch:
```

Excerpt of the aggregate gate (`.github/workflows/ci.yml`, `required` job):

```yaml
  required:
    name: Required
    if: ${{ always() }}
    needs: [tests, lint, package, docs]
    runs-on: ubuntu-latest
    timeout-minutes: 2

    steps:
      - name: Verify required jobs passed
        env:
          TESTS_RESULT: ${{ needs.tests.result }}
          LINT_RESULT: ${{ needs.lint.result }}
          PACKAGE_RESULT: ${{ needs.package.result }}
          DOCS_RESULT: ${{ needs.docs.result }}
        run: |
          test "$TESTS_RESULT" = "success"
          test "$LINT_RESULT" = "success"
          test "$PACKAGE_RESULT" = "success"
          test "$DOCS_RESULT" = "success"
```

Note `complexity` is absent from both `needs:` and the `run:` assertions.

Verified facts about the repository (from `gh`, at plan time):
- Default branch: `develop`.
- Recent merged PR base branches: all `develop`.
- `gh api repos/ser888gio/agent-testkit/branches/develop/protection` returns
  `404 Branch not protected`.

### Repo conventions

Actions are pinned to full commit SHAs with a trailing `# vN` comment (e.g.
`actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v5`). Preserve
that. Two-space YAML indent. Do not upgrade or re-pin any action in this plan.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python -m pytest` | exit 0, `955 passed` |
| Lint | `python -m ruff check .` | `All checks passed!` |
| YAML sanity | `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"` | exit 0, no output |
| Default branch | `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` | `develop` |
| Workflow runs | `gh run list --workflow=ci.yml --limit 5` | (see steps) |

## Scope

**In scope** (the only files you should modify):
- `.github/workflows/ci.yml`
- `.github/workflows/security.yml`

**Out of scope** (do NOT touch, even though they look related):
- Any job's `steps:` — the job bodies are correct and tested. This plan changes
  triggers and the `required` gate wiring only.
- Action version pins — leave every `uses:` line byte-identical.
- The `schedule:` cron in `security.yml` — it works and is the only thing that
  has been running.
- `.pre-commit-config.yaml` — a separate concern; do not extend it here.
- Repository settings on GitHub (branch protection) — **this is a maintainer
  action, not an executor action.** See "Maintainer follow-up" below. Do not
  run any `gh api` call that writes.

## Git workflow

- Branch: `chore/007-ci-actually-runs` (already created off `develop`).
- Suggested commit: `ci: run the workflows on develop, gate on complexity`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm the suite is green before touching CI

This plan is only safe on a green suite (see "Why this matters").

```
python -m pytest -q
```

**Verify**: `955 passed`, 0 failed. If anything fails, **STOP** — plan 006 has
not landed, and this plan must not proceed.

### Step 2: Add `develop` to both workflow triggers

In `.github/workflows/ci.yml`, change the `on:` block to:

```yaml
on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [main, develop]
  workflow_dispatch:
```

Apply the identical change to the `pull_request` and `push` branch lists in
`.github/workflows/security.yml`, leaving its `schedule:` and
`workflow_dispatch:` entries exactly as they are.

Keep `main` in both lists: it costs nothing and keeps the workflows correct if
the default branch changes later.

**Verify**:
```
python -c "import yaml; [yaml.safe_load(open(f)) for f in ['.github/workflows/ci.yml','.github/workflows/security.yml']]"
grep -n "branches: \[main, develop\]" .github/workflows/ci.yml .github/workflows/security.yml
```
→ the Python call exits 0 silently; grep returns **four** matches (two per file).

### Step 3: Add `complexity` to the required gate

In `.github/workflows/ci.yml`, in the `required` job:

1. Add `complexity` to the `needs:` list:
   ```yaml
    needs: [tests, lint, complexity, package, docs]
   ```
2. Add a matching env var and assertion, following the exact style of the four
   already there:
   ```yaml
        env:
          TESTS_RESULT: ${{ needs.tests.result }}
          LINT_RESULT: ${{ needs.lint.result }}
          COMPLEXITY_RESULT: ${{ needs.complexity.result }}
          PACKAGE_RESULT: ${{ needs.package.result }}
          DOCS_RESULT: ${{ needs.docs.result }}
        run: |
          test "$TESTS_RESULT" = "success"
          test "$LINT_RESULT" = "success"
          test "$COMPLEXITY_RESULT" = "success"
          test "$PACKAGE_RESULT" = "success"
          test "$DOCS_RESULT" = "success"
   ```

Do not change the complexity job itself, its `max_complexity_allowed: 26`, or
its action pin.

**Verify**:
```
grep -n "complexity" .github/workflows/ci.yml
```
→ shows the job definition, the `needs:` entry, the `COMPLEXITY_RESULT` env
line, and the `test "$COMPLEXITY_RESULT"` assertion.

### Step 4: Confirm the complexity gate would actually pass

The complexity job has never run in CI, so its ceiling of 26 is unverified
against the current codebase. Check it locally before making it blocking:

```
python -m complexipy . --max-complexity-allowed 26
```

**Verify**: exit 0.

If it exits non-zero, **STOP and report** the offending functions. Do NOT raise
`max_complexity_allowed` to make it pass — that silently weakens the gate this
plan exists to strengthen, and picking a new ceiling is a maintainer decision.

### Step 5: Final verification

```
python -m pytest -q
python -m ruff check .
```

**Verify**: `955 passed`; ruff `All checks passed!`. Neither should be affected
by this plan — you are confirming you did not disturb anything.

## Test plan

There are no repo tests for workflow YAML, and this plan does not add any —
asserting on CI config from pytest would test a fixture, not the pipeline.

Verification is instead structural (the greps in steps 2–3) plus the real
proof, which only arrives after merge: the first pull request into `develop`
must show CI checks attached. Record that as the acceptance signal in your
report; do not attempt to trigger it yourself.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest` exits 0, `955 passed`
- [ ] `python -m ruff check .` exits 0
- [ ] Both workflow files parse as YAML (step 2 command exits 0)
- [ ] `grep -c "branches: \[main, develop\]" .github/workflows/ci.yml` returns `2`
- [ ] `grep -c "branches: \[main, develop\]" .github/workflows/security.yml` returns `2`
- [ ] `grep -c "COMPLEXITY_RESULT" .github/workflows/ci.yml` returns `2`
- [ ] `needs:` in the `required` job lists all five jobs
- [ ] `python -m complexipy . --max-complexity-allowed 26` exits 0
- [ ] `git status --short` shows exactly two modified files and no others
- [ ] `plans/README.md` status row for 007 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 shows any failing test — plan 006 has not landed. Do not proceed.
- Step 4's complexity check fails. Report the functions over the ceiling; do
  not adjust the ceiling.
- The default branch is no longer `develop`
  (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`) — the
  premise of this plan has changed.
- Either workflow file no longer matches the "Current state" excerpts.
- You find yourself wanting to edit a job's `steps:` to make something pass.

## Maintainer follow-up (NOT for the executor)

Two items require repository-admin rights and an explicit human decision. The
executor must **not** perform these; they are recorded here so they are not
lost.

1. **Enable branch protection on `develop`.** Currently
   `gh api repos/ser888gio/agent-testkit/branches/develop/protection` returns
   `404 Branch not protected`, so even a correct workflow does not block a
   merge. Once step 2 has landed and one PR has run CI green (so the check name
   is registered), require the `Required` check. This is an outward-facing
   repository settings change and should be made deliberately by the
   maintainer.

2. **Add a notification path for scheduled failures.** The weekly `Security`
   workflow failed on 2026-08-10, 08-17 and 08-24 (`cryptography 49.0.0`,
   PYSEC-2026-3552) and nobody noticed for three weeks. That specific
   vulnerability has since self-resolved — `uv.lock` now pins `cryptography`
   50.0.0 — but the visibility gap remains: a cron job whose failure reaches
   nobody is not a control.

## Maintenance notes

- `permissions: contents: read` is correct and should stay. Nothing in this
  plan needs write scope.
- The `concurrency` group keys on `github.ref`, so adding `develop` will not
  cause runs to cancel each other across branches.
- Expect the first few `develop` PRs after this lands to surface latent
  failures that have accumulated while CI was dark — particularly in the
  `docs` job (`npm run build` with `onBrokenLinks: throw`) and the `package`
  job, neither of which has run against recent commits. That is the gate doing
  its job; budget time for it rather than treating it as a regression from
  this plan.
- Reviewer should scrutinize: that no action pin changed, and that the
  `required` job's `run:` assertions and `env:` block stayed in sync (a missing
  `test` line silently drops a job from the gate — the exact bug this plan
  fixes for `complexity`).
