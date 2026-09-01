# Plan 012: Make the Complexity CI job actually enforce its threshold

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 9a27225..HEAD -- .github/workflows/ci.yml frontend/agentaudit/web/api.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (independent of plan 011 — different files; both are
  required before the `required` gate can go green)
- **Category**: dx
- **Planned at**: commit `9a27225`, 2026-09-01

## Why this matters

The `Complexity` job in `.github/workflows/ci.yml` has **failed on every CI run
that has ever executed** — twelve consecutive runs since CI was switched on for
`develop` on 2026-08-31. It is one of two jobs still red (plan 011 owns the
other), and the `required` gate aggregates both, so no pull request can show a
green build until both land.

It is not flaky and it is not a genuine complexity violation. The job is
misconfigured in a way that makes its configured threshold a no-op:

**`rohaquinlop/complexipy-action@v3` has no `max_complexity_allowed` input.**

`v3` is a tag from 2025-07-06 that has never moved; the action's project is now
on v7.0.1. The v3 `action.yml` declares only `paths`, `output_csv`,
`output_json`, `ignore_complexity`, `details`, `quiet`, `sort`. GitHub Actions
silently ignores a `with:` key that an action does not declare, so the
workflow's `max_complexity_allowed: 26` was never passed to anything. v3's
Dockerfile pins `complexipy==3.1.0`, whose built-in default threshold is **15**.
The repo's most complex function measured 21 under that version — over 15, so
the tool exits non-zero and the job fails, every time, while printing a
reassuring "Analysis completed!" and a table whose numbers all look fine
against the 26 nobody was comparing to.

So the gate the repo believes it has (fail above 26) has never existed. What it
actually had was an invisible, unconfigurable gate at 15 that it has always
been failing. Fixing this both greens the build and gives the repo the
threshold it intended.

## Current state

### Files

- `.github/workflows/ci.yml` — the `complexity` job, lines 68–84.
- `frontend/agentaudit/web/api.py` — contains `connect_options`, the one
  function that exceeds 26 under the corrected tool version.

### The misconfigured job, exactly as it exists today

Excerpt (`.github/workflows/ci.yml:68-84`, verified at `9a27225`):

```yaml
  complexity:
    name: Complexity
    runs-on: ubuntu-latest
    timeout-minutes: 5

    steps:
      - name: Check out repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v5
        with:
          persist-credentials: false

      - name: Run complexipy
        uses: rohaquinlop/complexipy-action@v3
        with:
          paths: .
          max_complexity_allowed: 26
          output_json: true
```

Note that `actions/checkout` on line 75 is pinned to a full commit SHA with a
version comment. **Every other action in this workflow follows that
convention** — `astral-sh/setup-uv`, `actions/setup-node`. The complexipy
action on line 80 is the sole exception, pinned to a mutable tag. Fixing that
is part of this plan.

### What the correct version provides

`rohaquinlop/complexipy-action@v7.0.1` declares `max_complexity_allowed` as a
real input and its entrypoint maps it to complexipy's `-mx` flag. It also keeps
`paths` and `output_json` with the same names and meanings, so the existing
`with:` block needs no restructuring — only the version changes.

The v7.0.1 tag resolves to commit
`e2b05bcc06d899a24e2b6bb8b1354ac42800a95e`. Its Dockerfile pins
`complexipy==7.0.1`.

### The one function over the threshold

complexipy 7.0.1 scores cognitive complexity differently from 3.1.0, so the old
numbers do not carry over. Measured across the full CI scope (all 156 tracked
`.py` files — `agentaudit backend frontend infra tests`) at `9a27225`, exactly
one function exceeds 26:

```
frontend/agentaudit/web/api.py
    connect_options 27  ❌ FAILED
```

Everything else in the repo passes at 26. This is a single-function fix, one
point over the line.

Excerpt (`frontend/agentaudit/web/api.py:563-625`, verified at `9a27225`):

```python
@router.get("/connect-options")
def connect_options(principal: Principal = Depends(current_principal)) -> dict:  # noqa: ARG001
    root = PACKAGE_DIR.parent
    targets = sorted(
        p.relative_to(root).as_posix()
        for p in (PACKAGE_DIR / "config").glob("*.yaml")
        if _is_offerable_target(p)
    )
    pack_roots = sorted(
        p.relative_to(root).as_posix() for p in (PACKAGE_DIR / "packs").iterdir() if is_pack_dir(p)
    )
    pack_tests: dict[str, list[dict]] = {}
    for rel in pack_roots:
        try:
            cases = discover(str(root / rel))
        except LoaderError:
            continue
        pack_tests[rel] = [
            {
                "id": t.id,
                "description": t.description,
                "category": t.category.value,
                "risk": t.risk.value,
            }
            for t in cases
            if isinstance(t, TestCase)
        ]
    store = get_store()
    # Targets the tenant registered by endpoint URL: runnable straight from
    # their stored rows, no shipped config needed.
    registered_targets = [
        {"id": row.id, "name": row.name} for row in store.list_targets(principal.org_id)
    ]
    # Default to whatever this org last launched -- derived, not a stored
    # preference.
    last_jobs = store.jobs.list_recent(principal.org_id, limit=1)
    default_target = default_pack = None
    if last_jobs:
        for rel in targets:
            try:
                raw = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if isinstance(raw, dict) and str(raw.get("id")) == last_jobs[0].target_id:
                default_target = rel
                break
        else:
            default_target = next(
                (t["id"] for t in registered_targets if t["id"] == last_jobs[0].target_id),
                None,
            )
        default_pack = next(
            (rel for rel in pack_roots if Path(rel).name == last_jobs[0].pack_id),
            None,
        )
    return {
        "targets": targets,
        "registered_targets": registered_targets,
        "pack_roots": pack_roots,
        "default_target": default_target,
        "default_pack": default_pack,
        "pack_tests": pack_tests,
    }
```

The complexity lives in two independent blocks: the `pack_tests` accumulation
loop, and the `for/else` + `next(...)` default-derivation. Both are
self-contained and lift out cleanly.

### Repo conventions to match

- **Keep `frontend/agentaudit/web/app.py` and `api.py` thin** — CLAUDE.md's
  standing recommendation is to push logic into `core/`. This plan does *not*
  do that (see Maintenance notes for why); it extracts module-private helpers
  within `api.py`, which is the smaller, lower-risk move.
- Module-private helpers in `api.py` are named with a leading underscore and
  defined at module level, above or near their caller. See `_is_offerable_target`
  in the same file for the pattern.
- Comments explain *why*. Preserve the two existing explanatory comments
  ("Targets the tenant registered by endpoint URL…" and "Default to whatever
  this org last launched…") — move them with the code they describe.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Complexity, CI scope | `PYTHONIOENCODING=utf-8 uvx complexipy@7.0.1 agentaudit backend frontend infra tests -mx 26` | exit 0, no `FAILED` rows |
| Complexity, offenders only | `PYTHONIOENCODING=utf-8 uvx complexipy@7.0.1 agentaudit backend frontend infra tests -mx 26 -f -s desc` | no functions listed |
| Web/API tests | `python -m pytest tests/test_web.py tests/test_api.py` | all pass |
| Lint | `python -m ruff check .` | exit 0, "All checks passed" |
| Format check | `python -m ruff format --check frontend/agentaudit/web/api.py` | exit 0 |
| Full suite | `python -m pytest` | 0 failed (~6 min) |

**On `uvx`**: it runs complexipy from an ephemeral environment and installs
nothing into the project. `PYTHONIOENCODING=utf-8` is required on Windows —
without it the tool crashes with `UnicodeEncodeError: 'charmap' codec can't
encode character '✅'` while printing its check-mark glyphs. That crash is
a console encoding problem, not a complexity failure; do not misread it.

**Windows note**: call pytest and ruff as modules (`python -m pytest`), never as
console scripts. `uv run --frozen --extra dev pytest` fails on Windows with
`uv trampoline failed to canonicalize script path`. CI runs the console-script
form on Linux, where it is fine.

**If `tests/test_api.py` does not exist**, run only `tests/test_web.py`; the API
router's coverage lives there. Check with `ls tests/test_api.py` first rather
than assuming.

## Scope

**In scope** (the only files you may modify):

- `frontend/agentaudit/web/api.py` — extract two helpers from `connect_options`.
- `.github/workflows/ci.yml` — the `uses:` line of the `Run complexipy` step
  only (line 80).

**Out of scope** (do NOT touch, even though they look related):

- The JSON response shape of `/api/connect-options`. The SPA's
  `frontend/spa/src/pages/AgentConnect.tsx` consumes all six keys. The
  returned dict must be byte-for-byte equivalent; this is a pure refactor.
- Any other function in `api.py`. Only `connect_options` is over the
  threshold. Reducing complexity elsewhere is not asked for and widens review
  for no gain.
- `max_complexity_allowed: 26` itself. Do **not** raise the threshold to make
  the job pass — that inverts the plan. 26 is the repo's chosen number; the
  code comes to it, not the other way round.
- The other jobs in `ci.yml` (`tests`, `lint`, `package`, `docs`, `required`).
  `Lint`, `Build package` and `Build docs site` are already green. `Tests` is
  red and is plan 011's, not yours.
- `tests/test_phase2_infra.py` — plan 011 owns it.

## Git workflow

- Branch: `fix/012-complexity-gate`, cut from `develop`.
- Two commits, one per step, or one combined — either is fine. Message style is
  conventional commits, see `git log --oneline`, e.g.
  `fix(web): mark API responses no-store`. Suggested:
  `refactor(web): split connect_options into two helpers` and
  `ci: pin complexipy-action to v7.0.1 so the threshold applies`.
- Repo commit trailers are required. End each commit message with:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Extract two helpers from `connect_options`

Do this step **first**. It is verifiable entirely locally; the workflow change
in step 2 is not.

In `frontend/agentaudit/web/api.py`, add two module-level private helpers
immediately above the `@router.get("/connect-options")` decorator, and rewrite
`connect_options` to call them. The target shape:

```python
def _pack_tests(root: Path, pack_roots: list[str]) -> dict[str, list[dict]]:
    """Test metadata for every discoverable pack, keyed by pack path."""
    pack_tests: dict[str, list[dict]] = {}
    for rel in pack_roots:
        try:
            cases = discover(str(root / rel))
        except LoaderError:
            continue
        pack_tests[rel] = [
            {
                "id": t.id,
                "description": t.description,
                "category": t.category.value,
                "risk": t.risk.value,
            }
            for t in cases
            if isinstance(t, TestCase)
        ]
    return pack_tests


def _defaults_from_last_job(
    root: Path,
    targets: list[str],
    pack_roots: list[str],
    registered_targets: list[dict],
    last_job,
) -> tuple[str | None, str | None]:
    """The (target, pack) to preselect, derived from this org's last job.

    A shipped config file wins when one carries the job's target id; otherwise
    the id is matched against the tenant's registered rows.
    """
    for rel in targets:
        try:
            raw = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(raw, dict) and str(raw.get("id")) == last_job.target_id:
            default_target = rel
            break
    else:
        default_target = next(
            (t["id"] for t in registered_targets if t["id"] == last_job.target_id),
            None,
        )
    default_pack = next(
        (rel for rel in pack_roots if Path(rel).name == last_job.pack_id),
        None,
    )
    return default_target, default_pack


@router.get("/connect-options")
def connect_options(principal: Principal = Depends(current_principal)) -> dict:  # noqa: ARG001
    root = PACKAGE_DIR.parent
    targets = sorted(
        p.relative_to(root).as_posix()
        for p in (PACKAGE_DIR / "config").glob("*.yaml")
        if _is_offerable_target(p)
    )
    pack_roots = sorted(
        p.relative_to(root).as_posix() for p in (PACKAGE_DIR / "packs").iterdir() if is_pack_dir(p)
    )
    pack_tests = _pack_tests(root, pack_roots)
    store = get_store()
    # Targets the tenant registered by endpoint URL: runnable straight from
    # their stored rows, no shipped config needed.
    registered_targets = [
        {"id": row.id, "name": row.name} for row in store.list_targets(principal.org_id)
    ]
    # Default to whatever this org last launched -- derived, not a stored
    # preference.
    last_jobs = store.jobs.list_recent(principal.org_id, limit=1)
    default_target = default_pack = None
    if last_jobs:
        default_target, default_pack = _defaults_from_last_job(
            root, targets, pack_roots, registered_targets, last_jobs[0]
        )
    return {
        "targets": targets,
        "registered_targets": registered_targets,
        "pack_roots": pack_roots,
        "default_target": default_target,
        "default_pack": default_pack,
        "pack_tests": pack_tests,
    }
```

Details that matter:

- The `for ... else` in `_defaults_from_last_job` is load-bearing. The `else`
  runs only when the loop completes **without** `break` — i.e. no shipped
  config matched — and that is what makes the registered-targets lookup a
  fallback rather than an override. Do not restructure it into an `if`.
- `_defaults_from_last_job` takes `last_job` (a single row), not `last_jobs`
  (the list). The caller passes `last_jobs[0]` and keeps the emptiness check.
  Leave `last_job` untyped; the row type is not imported in this module and
  adding an import for an annotation is out of scope.
- `Path` and `yaml` are already imported in `api.py`. Do not add imports. If
  ruff reports an unused or missing import after your edit, you have changed
  something you should not have.
- Return the tuple in `(default_target, default_pack)` order and unpack in the
  same order.

**Verify**:

- `PYTHONIOENCODING=utf-8 uvx complexipy@7.0.1 agentaudit backend frontend infra tests -mx 26 -f -s desc`
  → no functions listed, exit 0. (Measured on the target shape above: 
  `connect_options` 6, `_pack_tests` 6, `_defaults_from_last_job` 10 — all far
  under 26.)
- `python -m ruff check .` → `All checks passed!`
- `python -m ruff format --check frontend/agentaudit/web/api.py` → exit 0. If it
  reports the file would be reformatted, run
  `python -m ruff format frontend/agentaudit/web/api.py` and re-check.
- `python -m pytest tests/test_web.py` → all pass.

### Step 2: Pin the action to v7.0.1 by SHA

In `.github/workflows/ci.yml`, change **only** line 80:

```yaml
        uses: rohaquinlop/complexipy-action@v3
```

to:

```yaml
        uses: rohaquinlop/complexipy-action@e2b05bcc06d899a24e2b6bb8b1354ac42800a95e # v7.0.1
```

Leave the `with:` block (`paths: .`, `max_complexity_allowed: 26`,
`output_json: true`) exactly as it is — all three inputs exist in v7.0.1 with
the same names.

The trailing `# v7.0.1` comment is required: it matches how every other action
in this file is pinned, and it is the only thing that makes the SHA readable to
a human.

**Verify**:

- `grep -n "complexipy-action" .github/workflows/ci.yml` → exactly one match,
  showing the 40-character SHA and the `# v7.0.1` comment.
- `grep -cE "uses: .*@[0-9a-f]{40}" .github/workflows/ci.yml` → `7` (six
  pre-existing SHA-pinned uses plus the one you just added). If the count is
  lower, you edited the wrong line.
- `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml',encoding='utf-8')); print('valid yaml')"`
  → `valid yaml`

### Step 3: Confirm nothing else regressed

**Verify**: `python -m pytest` → `0 failed`.

Expect `tests/test_phase2_infra.py::test_compose_enables_oidc_and_binds_public_services_to_loopback`
to **still fail** unless plan 011 has already landed on your branch. That one
failure is expected and is not yours. Any *other* failure is a STOP condition.

## Test plan

No new tests. Step 1 is a pure refactor with an unchanged response shape, and
step 2 changes CI configuration, which pytest does not exercise.

The existing coverage is the safety net:

- `tests/test_web.py` covers the `/api/connect-options` route through a
  FastAPI `TestClient`. It must pass unchanged — that is the evidence the
  refactor preserved behavior.
- The complexity command in step 1 is the regression check for the thing this
  plan is actually about.

To confirm the refactored helpers are genuinely exercised rather than dead,
run `python -m pytest tests/test_web.py -k connect` and confirm at least one
test is collected and passes. If zero tests match, report that in your summary —
it means `/api/connect-options` has no direct coverage and the refactor rests
on the broader `test_web.py` suite alone. Do not write new tests to close that
gap; note it and move on.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `PYTHONIOENCODING=utf-8 uvx complexipy@7.0.1 agentaudit backend frontend infra tests -mx 26`
      exits 0 with no `FAILED` rows
- [ ] `python -m ruff check .` exits 0
- [ ] `python -m ruff format --check frontend/agentaudit/web/api.py` exits 0
- [ ] `python -m pytest tests/test_web.py` exits 0
- [ ] `python -m pytest` reports no failures other than (at most) the plan-011
      compose test
- [ ] `grep -n "complexipy-action@v3" .github/workflows/ci.yml` returns no
      matches
- [ ] `grep -n "max_complexity_allowed: 26" .github/workflows/ci.yml` still
      returns one match (the threshold was not raised)
- [ ] `git status --porcelain` lists only `frontend/agentaudit/web/api.py` and
      `.github/workflows/ci.yml`
- [ ] `plans/README.md` status row for 012 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows either in-scope file changed since `9a27225`, or the
  `connect_options` excerpt above does not match what you find.
- After step 1, complexipy still reports a function over 26. Report which
  function and its score; do not start refactoring additional functions, and
  do not raise the threshold.
- `python -m pytest tests/test_web.py` fails after step 1. The refactor was
  meant to be behavior-preserving; a failure means it was not, and guessing at
  a fix risks changing the API response shape.
- You cannot run `uvx` (no `uv` on PATH). Report it rather than substituting a
  `pip install complexipy` into the project environment — that would mutate the
  dev environment for a read-only check.
- The v7.0.1 SHA `e2b05bcc06d899a24e2b6bb8b1354ac42800a95e` does not resolve.
  Verify with
  `gh api repos/rohaquinlop/complexipy-action/git/ref/tags/v7.0.1 -q '.object.sha'`
  and report a mismatch rather than substituting a tag.
- Making the job pass appears to require editing `max_complexity_allowed`.

## Maintenance notes

For whoever owns this next:

- **This gate has never enforced anything, so treat the first green run as a
  new baseline, not a return to normal.** Functions written between CI being
  enabled and this plan landing were never checked against 26.
- **The threshold is now real and it is tight.** `connect_options` was one
  point over. After this plan the highest remaining score is well under 26, but
  a reviewer should expect this job to start failing on genuinely complex new
  code — which is the point. When it does, the fix is to split the function,
  not to raise the number.
- **Complexity scores are version-coupled.** complexipy 3.1.0 and 7.0.1 score
  the same code differently (the repo's peak moved from 21 to 27 across that
  upgrade). Because the action is now SHA-pinned, scores are reproducible;
  any future bump of that pin should be accompanied by a fresh local
  measurement, since the numbers can shift under you.
- **What a reviewer should scrutinize**: that `_defaults_from_last_job`
  preserves the `for/else` fallback semantics, and that the six keys of the
  `/api/connect-options` response are unchanged in name and order.
- **Deliberately deferred**: CLAUDE.md recommends pushing logic out of
  `frontend/agentaudit/web/` into `core/`, where it is testable without a
  `TestClient`. `_defaults_from_last_job` is a reasonable candidate — it is
  pure derivation over a store row. That move is not in this plan because it
  would change the dependency graph and needs its own test file; this plan
  stays a local extraction so the CI fix is not held hostage to a refactor
  debate.
- The `required` gate also needs plan 011 (the `Tests` job). Neither plan alone
  produces a green build.
