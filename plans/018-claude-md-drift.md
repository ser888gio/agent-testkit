# Plan 018: Correct the four false statements in `CLAUDE.md` and the stale `web` entry in `components.yaml`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7cb6196..HEAD -- CLAUDE.md docs/components.yaml tools/validate.sh`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `7cb6196`, 2026-09-04

## Why this matters

Doc drift is usually low priority. This instance is not, because `CLAUDE.md` is
the file coding agents read *instead of* looking at the repository. Four of its
statements are verifiably false at commit `7cb6196`, and one of them actively
instructs an agent to delete working, tested, documented code:

> There is **no `examples/` directory** — it held only stale `__pycache__` and
> was removed.

`examples/` exists, is git-tracked (8 files), is linked from `README.md` as
"three runnable quickstarts", and *is* wired into CI via `tests/test_examples.py`
— whose docstring says "The examples exist so a new user can copy-paste them; if
they rot, they are worse than no examples." An agent that trusts `CLAUDE.md`
will delete the directory and break the suite.

The test count is off by 358 and the duration by roughly 2x, which makes any
"did I break something?" sanity check meaningless. The repo map describes a
server-side template layer that does not exist, and names two of five domain
packages. `docs/components.yaml` — the machine-readable map `CLAUDE.md` points
agents at — describes the web component as one file when it is four, and omits
`auth.py` entirely, which is the multi-tenant boundary every route depends on.

Measured facts, all captured at `7cb6196`:

```
$ python -m pytest --collect-only -q | tail -1
1066 tests collected in 1.78s

$ python -m pytest -q | tail -1
1066 passed, 26 warnings in 682.15s (0:11:22)

$ git ls-files examples
examples/README.md
examples/external-redteam/README.md
examples/http-endpoint/README.md
examples/http-endpoint/target.yaml
examples/treasury-demo/README.md
examples/treasury-demo/hardened-treasury-agent.yaml
examples/treasury-demo/pack/unapproved_invoice.yaml
examples/treasury-demo/unsafe-treasury-agent.yaml

$ ls frontend/agentaudit/web/
__init__.py  api.py  app.py  auth.py  CLAUDE.md  runtime.py  spa_dist/

$ ls backend/agentaudit/domains/
__init__.py  CLAUDE.md  declarative/  email/  mcp/  support/  treasury/
```

## Current state

Files involved:

- `CLAUDE.md` — the project instruction file. Four corrections.
- `docs/components.yaml` — the machine-readable component map. One correction.
- `tools/validate.sh` — one contradictory comment. One correction.

### Correction 1 — `CLAUDE.md:141`, the test count and duration

```
| Unit tests (full suite, 708 tests, ~3-6 min) | `python -m pytest` |
```

Actual: 1066 tests, 11m22s measured on Windows at `7cb6196`.

Note there is a second stale duration claim at `CLAUDE.md:206` ("The full suite
is roughly 3-6 minutes") and a third in `CONTRIBUTING.md` ("~350s measured on
Windows"). All three disagree with each other and with reality.

### Correction 2 — `CLAUDE.md:176-179`, the `examples/` instruction

```
inside the same pytest suite. There is **no `examples/` directory** — it held only stale
`__pycache__` and was removed. The `agentaudit run ...` commands below are the maintained,
tested way to exercise the tool by hand; do not reintroduce example scripts without also
wiring them into CI, which is how the previous ones rotted unnoticed.
```

`examples/` was reintroduced and *was* wired into CI — `tests/test_examples.py`
runs in the same pytest suite. The advice's own condition has been met.

### Correction 3 — `CLAUDE.md:123`, the web layer

```
frontend/agentaudit/web/ app.py · templates/ · static/
```

There is no `templates/` and no `static/`. The directory holds `app.py`,
`api.py`, `auth.py`, `runtime.py` and the built `spa_dist/`. The dashboard is a
Vite-built React SPA in `frontend/spa/`, not server-side templates.

### Correction 4 — `CLAUDE.md:117-121`, the repo map's module lists

```
  core/                audit · agent · sandbox · schema · loader · runner · assertions
                       findings · scoring · redaction · compliance · regressions · store
                       profile · discovery · catalog · planner · adapters
                       adaptive · attacker · judge · jsonx
  domains/             treasury/ · email/  (Sandbox subclasses + demo agents)
```

`domains/` actually holds `treasury/`, `email/`, `mcp/`, `support/` and
`declarative/`. `core/` holds 38 modules; the map omits several substantial
ones, including `isolation.py` (846 lines, the process-isolation layer),
`evolve.py`, `campaign.py`, `archive.py`, `intake.py`, `runview.py`, `llm.py`,
`egress.py`, `credentials.py` and `incidents.py`. The full current list:

```
adapters adaptive agent archive artifacts assertions attacker attacks audit
campaign catalog compliance config credentials deepeval_adapter discovery
egress evolve findings incident_promotion incidents intake isolation jsonx
judge llm loader planner profile redaction regressions runner runview sandbox
schema scoring store timeline
```

The repo map also omits `backend/agentaudit/worker.py` (545 lines), the job
execution engine.

### Correction 5 — `docs/components.yaml:145-155`, the `web` component

```yaml
  web:
    path: frontend/agentaudit/web
    import_path: agentaudit.web
    type: application
    owns:
      - FastAPI dashboard: run history, pass/fail matrix, test detail, run comparison
      - Run harness (re-run) endpoints
    entry_points:
      - frontend/agentaudit/web/app.py
      - infra/dev.sh                          # launches it locally
```

`api.py` is 857 lines with roughly 29 routes; `auth.py` is 497 lines
implementing the principal/org model every route depends on; `runtime.py` holds
`get_store`/`get_artifacts_dir`. None appear. The file's own header says
"Update this file when component boundaries, entry points, or dependencies
change."

### Correction 6 — `tools/validate.sh:12`

```
The full suite runs in a few seconds, so `--affected` is for tight iteration loops;
prefer the default before declaring work complete.
```

The recommendation is backwards: the full suite is ~11 minutes, so `--affected`
is the right choice *while iterating*, and the full suite is what you run before
declaring done — which is exactly what `CLAUDE.md`'s validation ladder already
says.

## Commands you will need

| Purpose             | Command                                             | Expected on success     |
|---------------------|-----------------------------------------------------|-------------------------|
| Count tests         | `python -m pytest --collect-only -q \| tail -1`      | `NNNN tests collected`  |
| List examples       | `git ls-files examples`                              | 8 tracked files         |
| List web dir        | `ls frontend/agentaudit/web/`                        | 4 `.py` + `spa_dist/`   |
| List domains        | `ls backend/agentaudit/domains/`                     | 5 package dirs          |
| Examples test       | `python -m pytest tests/test_examples.py`            | all pass                |
| Lint                | `python -m ruff check .`                             | `All checks passed!`    |
| Full suite          | `python -m pytest`                                   | `1066 passed` (or more) |

**Windows note**: call pytest and ruff as modules (`python -m pytest`), never as
console scripts.

## Scope

**In scope** (the only files you should modify):

- `CLAUDE.md` — corrections 1–4
- `docs/components.yaml` — correction 5
- `tools/validate.sh` — correction 6 (the comment only)

**Out of scope** (do NOT touch, even though they look related):

- **Any source file.** This is a documentation-only plan. If you find yourself
  editing a `.py`, `.ts`, or `.tsx` file, stop.
- `examples/` — do not delete, move, or "tidy" it. Correcting the doc that
  told you to delete it is the entire point of this plan.
- The directory-level `CLAUDE.md` files under `backend/agentaudit/core/`,
  `backend/agentaudit/domains/`, `frontend/agentaudit/web/`, `agentaudit/packs/`
  and `tests/` — they may also have drifted, but auditing them is not in scope
  and would make this change unreviewable.
- `README.md` — its `examples/` link is already correct.
- `CONTRIBUTING.md` — it carries a third, different suite-duration figure.
  Leave it; see Maintenance notes.
- Do not restructure `CLAUDE.md`, reorder sections, or rewrite prose that is
  accurate. Change only what is factually wrong.

## Git workflow

- Branch off `develop`: `git checkout -b docs/018-claude-md-drift develop`
- Conventional-commit subject, e.g.
  `docs: correct the four stale claims in CLAUDE.md`
- Commit message must end with:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Re-measure before you write

Do not copy the numbers from this plan without checking them — this plan is
itself a document that can go stale.

```
python -m pytest --collect-only -q | tail -1
```

Record the collected count. Then run the full suite once and record the wall
time from its final line.

**Verify**: you have two fresh numbers. Use *those* in Step 2, not the ones in
this plan, if they differ.

### Step 2: Fix the test count and duration in `CLAUDE.md`

Update line 141's table row to the measured count and duration.

To stop this rotting again, prefer a form that does not require an exact
number — e.g. "~1.1k tests, ~11 min on Windows". A reader needs the order of
magnitude, not a figure that is wrong the week after it is written.

Then reconcile `CLAUDE.md:206` ("The full suite is roughly 3-6 minutes") with
the same measurement. Both statements must agree after this step.

**Verify**: `grep -n "708\|3-6 min" CLAUDE.md` → no matches.

### Step 3: Replace the `examples/` statement

Rewrite `CLAUDE.md:176-179` to state what is true: `examples/` exists, is
tracked, is linked from `README.md`, and is covered by `tests/test_examples.py`
in the same pytest suite.

Keep the *intent* of the original warning — it is still good advice — but attach
it to reality: example content must stay wired into the suite, because that is
what stopped the previous set rotting. Do not simply delete the paragraph; a
reader who saw the old claim needs the corrected one.

**Verify**:
- `grep -n "no .examples/. directory" CLAUDE.md` → no matches
- `grep -rn "examples" CLAUDE.md` → the remaining mentions describe it as
  existing and tested

### Step 4: Fix the web-layer line in the repo map

Replace `CLAUDE.md:123` so it names the files that exist:

```
frontend/agentaudit/web/ app.py · api.py · auth.py · runtime.py · spa_dist/ (built SPA)
```

Add a short note that the dashboard source is the React SPA in `frontend/spa/`
and that `spa_dist/` is its build output (gitignored, produced by
`npm run build`, asserted into the wheel by the CI `package` job) — so nobody
looks for a server-side template layer that was removed.

**Verify**: `grep -n "templates/ · static/" CLAUDE.md` → no matches.

### Step 5: Fix the `core/` and `domains/` module lists

Update `CLAUDE.md:117-121`:

- `domains/` must list all five: `treasury/ · email/ · mcp/ · support/ · declarative/`.
- `core/` must include the substantial omissions — at minimum `isolation`,
  `intake`, `runview`, `evolve`, `campaign`, `archive`, `llm`, `egress`,
  `credentials`. Re-derive the list yourself with
  `ls backend/agentaudit/core/*.py` rather than trusting this plan's copy.
- Add `worker.py` to the `backend/agentaudit/` block, described as the job
  execution engine.

Keep the existing visual format (` · `-separated names, wrapped and indented to
match the surrounding block). Do not convert it to a different layout.

**Verify**:
- `grep -n "isolation" CLAUDE.md` → at least one match in the repo map
- `grep -n "declarative" CLAUDE.md` → at least one match
- `grep -n "worker" CLAUDE.md` → at least one match in the repo map

### Step 6: Fix the `web` component in `docs/components.yaml`

Add `api.py`, `auth.py` and `runtime.py` to `entry_points`, and add multi-tenant
principal/org scoping to `owns`. Keep the existing YAML shape and comment style
(`infra/dev.sh` carries an inline `# launches it locally` comment; match that
register if you annotate).

Confirm the file still parses:

```
python -c "import yaml; d=yaml.safe_load(open('docs/components.yaml')); print(sorted(d['components']['web']['entry_points']))"
```

If the top-level key is not `components`, adjust the expression to match the
file's actual structure — read it first.

**Verify**: the command above prints a list containing `api.py`, `auth.py` and
`runtime.py` paths, and does not raise.

### Step 7: Fix the `tools/validate.sh` comment

Correct line 12 so the recommendation matches reality and matches `CLAUDE.md`'s
validation ladder: `--affected` while iterating, full suite before declaring
done.

Change the comment only. Do not change any shell logic in this file.

**Verify**:
- `grep -n "few seconds" tools/validate.sh` → no matches
- `git diff tools/validate.sh` → only comment lines changed

### Step 8: Validation

Documentation changes cannot break the suite, but run it once to confirm you did
not touch code by accident.

**Verify**:

- `git diff --name-only` → exactly `CLAUDE.md`, `docs/components.yaml`,
  `tools/validate.sh`
- `python -m ruff check .` → `All checks passed!`
- `python -m pytest tests/test_examples.py` → all pass (proof `examples/` is
  intact)

## Test plan

No new tests. This plan changes documentation only.

One optional hardening, at your discretion and only if it is a small change:
`tools/validate.sh` could assert the collected test count is within a stated
range, so the number in `CLAUDE.md` cannot silently rot again. If it is not
straightforward, skip it and note it in the Maintenance notes instead — a
brittle count assertion is worse than a slightly stale doc.

## Done criteria

ALL must hold:

- [ ] `grep -n "708" CLAUDE.md` → no matches
- [ ] `grep -n "no .examples/. directory" CLAUDE.md` → no matches
- [ ] `grep -n "templates/ · static/" CLAUDE.md` → no matches
- [ ] `grep -n "few seconds" tools/validate.sh` → no matches
- [ ] `grep -n "isolation" CLAUDE.md` and `grep -n "declarative" CLAUDE.md` each
      return at least one match
- [ ] `docs/components.yaml` parses as YAML and its `web` entry_points include
      `api.py`, `auth.py`, `runtime.py`
- [ ] `git diff --name-only` lists exactly the three in-scope files
- [ ] `python -m pytest tests/test_examples.py` passes and `examples/` is
      unchanged (`git status` shows no deletions)
- [ ] `plans/README.md` status row for 018 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `examples/` is not tracked, or `tests/test_examples.py` does not exist. That
  would mean the `CLAUDE.md` statement became true again since this plan was
  written, and correction 2 must be dropped rather than reversed.
- The measured test count in Step 1 differs from 1066 by more than ~10%. Use
  your measured number, but say so in your report — it means the suite moved
  substantially since this plan was written and other plans may be stale too.
- `docs/components.yaml` fails to parse after your edit and the cause is not an
  obvious indentation slip in your own change.
- You find a fifth incorrect statement in `CLAUDE.md`. Report it; do not fix it
  silently. The reviewer needs to know the scope grew.
- Fixing any of these appears to require changing a source file.

## Maintenance notes

- The failure mode here is specific: `CLAUDE.md` is read *instead of* the
  repository, so a wrong statement in it is worse than no statement. Exact
  counts and durations are the parts that rot fastest — prefer orders of
  magnitude ("~1.1k tests") over precise figures nobody will re-measure.
- Three files now carry a suite-duration figure: `CLAUDE.md` (twice),
  `CONTRIBUTING.md`, and `tools/validate.sh`. This plan reconciles the two in
  `CLAUDE.md` and fixes `validate.sh`. `CONTRIBUTING.md` is deliberately left
  out of scope to keep the diff reviewable — a follow-up should either align it
  or, better, reduce the number of places that state it to one.
- A reviewer should check that no source file appears in the diff, and that
  `examples/` is untouched.
- Deferred, and worth someone's attention later: the directory-level `CLAUDE.md`
  files under `backend/agentaudit/core/`, `backend/agentaudit/domains/`,
  `frontend/agentaudit/web/`, `agentaudit/packs/` and `tests/` were not audited
  and may carry their own drift. `docs/components.yaml` was checked only for its
  `web` component; the other components may be equally stale.
