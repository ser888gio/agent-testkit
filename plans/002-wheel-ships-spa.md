# Plan 002: Build the SPA before `uv build` so wheels ship a dashboard

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat e4cfe48..HEAD -- .github/workflows/ci.yml frontend/spa/package.json pyproject.toml`
> On any mismatch with "Current state" excerpts below, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx (packaging bug)
- **Planned at**: commit `e4cfe48`, 2026-08-26

## Why this matters

The CI `package` job builds wheels without building the React SPA first.
`frontend/agentaudit/web/spa_dist/` is gitignored, so a CI checkout has no
bundle; `pyproject.toml` declares `spa_dist/*` as package-data but packages an
empty directory. Every published wheel serves `_SPA_PLACEHOLDER`
("dashboard bundle is not built yet") forever — `agentaudit ui` appears broken
to every pip consumer while local dev works and hides it. This is a
presentation-blocking defect: the product cannot be demoed from an installed
wheel.

## Current state

- `.github/workflows/ci.yml` — jobs: tests / lint / package / docs. The
  `package` job (verified at commit `e4cfe48`) contains exactly:
  checkout (`actions/checkout@v5`, pinned SHA) → setup-uv → `uv build`.
  No Node step exists in that job.
- `frontend/spa/package.json` — Vite + React app. Build command is
  `npm run build`; output lands in `frontend/agentaudit/web/spa_dist/`.
- `pyproject.toml:71-72` — package-data declaration for `spa_dist/*`.
- The docs job already shows the repo's Node setup pattern:
  `actions/setup-node@<sha> # v4` with `node-version: "20"`,
  `cache: npm`, `cache-dependency-path`, then `npm ci` in a working-directory.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| SPA install/build (local) | `npm ci && npm run build` in `frontend/spa` | exit 0; `spa_dist/index.html` exists |
| Package (local)          | `uv build` | exit 0; wheel in `dist/` |
| Wheel inspection         | see Step 2 verify command | prints a non-empty namelist entry |
| Lint (YAML n/a)          | `uv run ruff check backend` | exit 0 |

## Scope

**In scope**:
- `.github/workflows/ci.yml` (the `package` job only)
- Optional: a packaging smoke assertion — prefer adding it to the existing
  test file that covers packaging concerns if one exists, else skip to Step 3
  verification only.

**Out of scope** (do NOT touch):
- `pyproject.toml` — package-data declaration is already correct.
- Any workflow other than the `package` job.
- SPA source code or its dependencies.

## Git workflow

- Branch: `advisor/002-wheel-ships-spa`
- Commit style: short imperative subject (repo example: `T18: fix SPA serving and session loading`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add Node build steps to the `package` job

In `.github/workflows/ci.yml`, inside the `package` job, after checkout and
BEFORE `uv build`, insert steps mirroring the docs job's established pattern:

```yaml
      - name: Install Node
        uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f8642d1e84afbd # v4 -- COPY the exact pinned SHA from the docs job, do not trust this excerpt
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/spa/package-lock.json

      - name: Build dashboard bundle
        run: npm ci && npm run build
        working-directory: frontend/spa
```

Important: copy the exact action version pin (full SHA) from the docs job's
existing `setup-node` step — this repo pins all actions by SHA.

**Verify**: locally reproduce what CI will do:
`cd frontend/spa && npm ci && npm run build` → exits 0 and creates
`frontend/agentaudit/web/spa_dist/index.html`. Then `uv build` → exits 0.

### Step 2: Verify the wheel actually contains the dashboard

Run the inspection one-liner:

```
uv run python -c "import zipfile, glob; w = sorted(glob.glob('dist/*.whl'))[-1]; names = [n for n in zipfile.ZipFile(w).namelist() if 'spa_dist/index.html' in n]; print(w); print(names); assert names, 'wheel missing spa_dist/index.html'"
```

**Verify**: prints the wheel path and a non-empty list. If empty, the
package-data glob or build output path is wrong — STOP (see conditions).

### Step 3: Confirm CI syntax

Validate the edited YAML parses:

```
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"
```

(If pyyaml isn't importable in the env, use `uv run --with pyyaml python -c ...`.)

**Verify**: prints `ok`.

## Test plan

- No unit-test changes required; the mechanical wheel-inspection assertion in
  Step 2 IS the regression check. Optionally add it to CI as a step after
  `uv build` in the same job so the guarantee holds on every future build:

  ```yaml
      - name: Assert wheel ships the dashboard
        run: uv run python -c "import zipfile, glob; w = sorted(glob.glob('dist/*.whl'))[-1]; assert [n for n in zipfile.ZipFile(w).namelist() if 'spa_dist/index.html' in n], 'missing spa_dist'"
  ```

## Done criteria

- [ ] `frontend/spa` npm build succeeds locally; `spa_dist/index.html` exists
- [ ] Wheel inspection assertion passes on a freshly built wheel
- [ ] ci.yml parses as valid YAML; only the `package` job was modified (`git diff --stat`)
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:
- The `package` job doesn't match the described shape (drift).
- `npm run build` fails or writes output somewhere other than
  `frontend/agentaudit/web/spa_dist/`.
- The wheel inspection stays empty after a successful build (packaging
  config issue beyond this plan's scope).
- You find yourself needing to edit `pyproject.toml`.

## Maintenance notes

- Reviewer should confirm the setup-node SHA matches the docs job's pin.
- If the SPA gains a second build target or the output dir moves, update both
  the cache-dependency-path and the wheel assertion together.
- Follow-up deferred: a friendly runtime error page when `spa_dist` is absent
  (replacing `_SPA_PLACEHOLDER`) — separate decision.
