# Plan 009: Stop nested git worktrees from polluting the working tree

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat 5959852..HEAD -- .gitignore`
> If `.gitignore` changed since this plan was written, compare the "Current
> state" excerpt against the live file before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `5959852`, 2026-08-29

## Why this matters

`git status` on a clean checkout reports `?? agent-testkit-wt/`. That directory
holds eight git worktrees checked out *inside* the repository:

```
agent-testkit-wt/prd008  [feat/prd-008-statistical-trial-policies]
agent-testkit-wt/prd009  [feat/prd-009-config-driven-verticals]
agent-testkit-wt/prd010  [feat/prd-010-iterative-attack-loop]
agent-testkit-wt/prd011  [feat/prd-011-step-level-timelines]
agent-testkit-wt/prd012  [feat/prd-012-core-pack-taxonomy]
agent-testkit-wt/prd013  [feat/prd-013-mcp-behavioral-pack]
agent-testkit-wt/prd015  [feat/prd-015-cost-and-positioning]
agent-testkit-wt/prd016  [feat/prd-016-incident-to-test-promotion]
```

`.gitignore` already covers the sibling convention — `.claude/worktrees/` is
listed — but not this one. The cost is a permanently dirty `git status`, which
trains everyone (human and agent) to ignore untracked output, and that is
exactly how a real stray file gets committed. It also gives `tools/affected.sh`
and any recursive tooling eight extra full checkouts to walk.

This is small and isolated. It is worth doing because it is the kind of noise
that makes every *other* plan's `git status` done-criterion less trustworthy.

## Current state

- `.gitignore` — repo-root ignore file.

Excerpt of the relevant section (`.gitignore`, verified at `5959852`):

```
# aislop runtime artifacts
**/.aislop/session.jsonl
.claude/worktrees/
```

`git check-ignore -v agent-testkit-wt` currently exits non-zero (no match).

Note the file also contains a cosmetic defect a few lines below, inside a
comment:

```
# React SPA (built artifacts are produced by 
pm run build in frontend/spa)
```

An `\n` escape was interpreted where `npm` was intended, splitting the comment
across two lines. It is inert — both lines are inside a comment — but it is in
scope for this plan since you are already editing the file.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Ignore check | `git check-ignore -v agent-testkit-wt` | exits 0, names the rule |
| Status | `git status --short` | no `?? agent-testkit-wt/` line |
| Worktree list | `git worktree list` | unchanged, all eight still listed |

## Scope

**In scope** (the only file you should modify):
- `.gitignore`

**Out of scope** (do NOT touch):
- **The worktrees themselves.** Do not run `git worktree remove`, do not delete
  `agent-testkit-wt/`, do not prune. Those are eight live feature branches with
  possibly-uncommitted work in them. This plan makes git *ignore* the
  directory; it does not clean it up. Removing them is the maintainer's call.
- `.claude/worktrees/` — already handled correctly.
- Any other section of `.gitignore` beyond the two edits named below.

## Git workflow

- Branch: `chore/009-ignore-nested-worktrees` (already created off `develop`).
- Suggested commit: `chore: ignore the nested worktree directory`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm the directory is currently untracked, not tracked

```
git ls-files agent-testkit-wt | head
```

**Verify**: no output. If any file under `agent-testkit-wt/` is tracked, STOP —
adding it to `.gitignore` would not untrack it, and removing tracked files is
out of scope.

### Step 2: Ignore the worktree directory

In `.gitignore`, extend the worktree section so it reads:

```
# aislop runtime artifacts
**/.aislop/session.jsonl

# Git worktrees checked out inside the repo (see `git worktree list`).
# The directories are live branch checkouts, not build output -- ignored so
# `git status` stays meaningful, never deleted automatically.
.claude/worktrees/
agent-testkit-wt/
```

**Verify**:
```
git check-ignore -v agent-testkit-wt
git status --short
```
→ `check-ignore` exits 0 and names `.gitignore` with the new rule;
`git status --short` no longer lists `?? agent-testkit-wt/`.

### Step 3: Repair the mangled comment

Fix the two-line comment so `npm` is intact and the comment is a single line:

```
# React SPA (built artifacts are produced by `npm run build` in frontend/spa)
```

Change only the comment text. The ignore patterns beneath it
(`node_modules/`, `frontend/spa/.vite/`,
`frontend/agentaudit/web/spa_dist/`) must stay exactly as they are.

**Verify**:
```
grep -n "npm run build" .gitignore
```
→ exactly one match, on a single line beginning with `#`.

### Step 4: Confirm nothing else changed

```
git diff --stat
git worktree list
```

**Verify**: `git diff --stat` shows `.gitignore` and nothing else;
`git worktree list` still shows all eight `agent-testkit-wt/*` entries plus the
`.claude/worktrees/*` ones — you must not have removed any.

## Test plan

No tests. This is a git configuration change with no runtime behavior; a pytest
assertion on `.gitignore` contents would test the fixture rather than anything
real.

Verification is the `git check-ignore` / `git status` pair in step 2, which is
a direct machine-checkable observation of the intended effect.

Run the suite once anyway to confirm you disturbed nothing:
`python -m pytest -q`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `git check-ignore -v agent-testkit-wt` exits 0
- [ ] `git status --short` contains no `agent-testkit-wt` line
- [ ] `grep -c "agent-testkit-wt/" .gitignore` returns `1`
- [ ] `grep -c "npm run build" .gitignore` returns `1`
- [ ] `git worktree list | grep -c agent-testkit-wt` returns `8`
- [ ] `git diff --name-only` lists only `.gitignore`
- [ ] `python -m pytest -q` is no worse than before your change
- [ ] `plans/README.md` status row for 009 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 shows tracked files under `agent-testkit-wt/`.
- `git worktree list` shows fewer than eight `agent-testkit-wt/*` entries after
  your change — you have removed a worktree, which is out of scope and may have
  destroyed uncommitted work.
- `.gitignore` does not match the "Current state" excerpt.
- Ignoring the directory causes any test to fail (it should not; if it does,
  something depends on that path being visible and the maintainer needs to know).

## Maintenance notes

- `agent-testkit-wt/` is a *convention*, not a git feature — the eight
  worktrees could equally live outside the repo, and there is a second set at
  `C:/Users/nicas/Desktop/agent-testkit-wt/` (a sibling of the repo, already
  outside it and therefore never a problem). If the maintainer standardizes on
  the sibling location, this ignore rule becomes dead and can be dropped.
- The worktrees are branch checkouts for PRD work. Several of those branches
  (`prd008`, `prd011`, `prd012`, `prd016`) correspond to work already merged to
  `develop`; those worktrees are probably prunable. Deliberately deferred out of
  this plan — pruning is destructive and needs a human to confirm nothing
  uncommitted is sitting in them.
- Reviewer should scrutinize: that the diff is `.gitignore`-only and that no
  `git worktree` command appears in the commit.
