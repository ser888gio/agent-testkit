# Plan 011: Re-align the Phase 2 infra contract test with hosted OIDC

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 9a27225..HEAD -- tests/test_phase2_infra.py infra/docker-compose.yml`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `9a27225`, 2026-09-01

## Why this matters

`python -m pytest` on `develop` is **1 failed, 979 passed**, and the CI `Tests`
job has failed on every run since CI was switched on. The single failure is
`tests/test_phase2_infra.py::test_compose_enables_oidc_and_binds_public_services_to_loopback`.

The product is not broken. Commit `a89708a` ("Make the container deployable
behind a reverse proxy") moved `infra/docker-compose.yml` from a hardcoded
local-Keycloak configuration to a hosted OIDC provider whose endpoints are
supplied from `infra/.env`. That was the right change. The test still asserts
the old hardcoded values and was never updated.

While this test is red, the `required` gate blocks every pull request, so no
other plan in this directory can be verified end to end. This is a prerequisite
for the rest of the queue.

The fix is **not** simply correcting one string. Python `assert` statements
short-circuit: the test dies on the first stale assertion, hiding two more
behind it. All three must be re-aligned in one pass, or the executor will fix
one and watch the next fail.

## Current state

### Files

- `tests/test_phase2_infra.py` — static assertions over the checked-in
  deployment contract. 87 lines, five test functions. Only the second one is
  stale; the other four pass and are out of scope.
- `infra/docker-compose.yml` — the deployment contract under test. **Read-only
  for this plan.** Do not edit it.

### The failing test, exactly as it exists today

Excerpt (`tests/test_phase2_infra.py:31-39`, verified at `9a27225`):

```python
def test_compose_enables_oidc_and_binds_public_services_to_loopback():
    services = _compose()["services"]
    environment = services["agentaudit"]["environment"]
    assert environment["AGENTAUDIT_AUTH_MODE"] == "oidc"
    assert environment["AGENTAUDIT_OIDC_AUDIENCE"] == "agentaudit-api"
    assert environment["AGENTAUDIT_OIDC_TOKEN_URL"].startswith("http://keycloak:8080/")
    assert services["agentaudit"]["ports"] == ["127.0.0.1:8000:8000"]
    assert services["keycloak"]["ports"] == ["127.0.0.1:8080:8080"]
    assert services["agentaudit"]["depends_on"]["keycloak"]["condition"] == "service_healthy"
```

### What the compose file actually says now

Verified by parsing `infra/docker-compose.yml` at `9a27225`:

| Assertion | Line | Live value | Verdict |
|---|---|---|---|
| `AGENTAUDIT_AUTH_MODE == "oidc"` | 34 | `oidc` | **passes — keep** |
| `AGENTAUDIT_OIDC_AUDIENCE == "agentaudit-api"` | 35 | `${AGENTAUDIT_OIDC_AUDIENCE:?set in infra/.env}` | **stale — fails** |
| `AGENTAUDIT_OIDC_TOKEN_URL.startswith("http://keycloak:8080/")` | 36 | `${AGENTAUDIT_OIDC_TOKEN_URL:?set in infra/.env}` | **stale — would fail** |
| `agentaudit.ports == ["127.0.0.1:8000:8000"]` | 37 | `['127.0.0.1:8000:8000']` | **passes — keep** |
| `keycloak.ports == ["127.0.0.1:8080:8080"]` | 38 | `['127.0.0.1:8080:8080']` | **passes — keep** |
| `agentaudit.depends_on["keycloak"]` | 39 | `depends_on` is `{"migrate": {...}}` only | **stale — would `KeyError`** |

Only line 35 appears in the current traceback because lines 36 and 39 are never
reached.

The `agentaudit` service's environment block now supplies **seven** OIDC
settings, every one of them in the `${NAME:?set in infra/.env}` form, plus
`AGENTAUDIT_SESSION_COOKIE_SECURE: ${AGENTAUDIT_SESSION_COOKIE_SECURE:-1}`.

### What the test is actually protecting

Re-aligning means preserving the *properties*, not the literals. The properties
worth keeping are:

1. The deployed app runs in `oidc` auth mode, never the loopback `dev` mode.
2. No OIDC setting has a baked-in default — Compose must refuse to start when
   the deployment has not supplied one. The `${NAME:?...}` form is what
   enforces that, and it is the direct replacement for asserting literals.
3. Session cookies default to secure.
4. Published ports stay bound to loopback (the reverse proxy terminates TLS).
5. The app starts only after migrations have completed.

Property 2 is *stronger* than what lines 35–36 asserted, and it is the reason
this test is worth keeping rather than deleting.

### Repo conventions to match

- One test file per module, `tests/test_<module>.py`. This file already exists;
  do not create a new one.
- Assertions are bare `assert` with no message unless the failure is
  non-obvious — see the four sibling tests in this same file.
- Comments explain *why* an assertion exists, not what it does. See
  `tests/test_phase2_infra.py:42-52` (`test_compose_requires_secrets_instead_of_shipping_defaults`)
  for the house style.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| This test file | `python -m pytest tests/test_phase2_infra.py` | 5 passed |
| The one test | `python -m pytest tests/test_phase2_infra.py -k oidc` | 1 passed |
| Lint | `python -m ruff check tests/test_phase2_infra.py` | exit 0, "All checks passed" |
| Format check | `python -m ruff format --check tests/test_phase2_infra.py` | exit 0 |
| Full suite | `python -m pytest` | 980 passed, 0 failed (~6 min) |

**Windows note:** call pytest and ruff as modules (`python -m pytest`), never as
console scripts. `uv run --frozen --extra dev pytest` fails on Windows with
`uv trampoline failed to canonicalize script path`. CI runs the console-script
form on Linux, where it is fine — do not "fix" the workflow.

## Scope

**In scope** (the only file you may modify):

- `tests/test_phase2_infra.py` — the body of
  `test_compose_enables_oidc_and_binds_public_services_to_loopback` only.

**Out of scope** (do NOT touch, even though they look related):

- `infra/docker-compose.yml` — the compose file is **correct**. The test is
  wrong. If you find yourself editing compose to satisfy the test, you have
  inverted the plan; STOP.
- `infra/.env.example` — no change needed.
- The other four tests in `tests/test_phase2_infra.py`. They pass today. In
  particular `test_compose_requires_secrets_instead_of_shipping_defaults` and
  `test_realm_uses_code_pkce_and_client_credentials_only` still assert the
  local Keycloak stack — that stack is scheduled for a separate decision (see
  Maintenance notes). Leave them exactly as they are.
- `.github/workflows/ci.yml` — the `Complexity` job is also red, for an
  unrelated reason. Plan 012 owns it. Do not touch the workflow.

## Git workflow

- Branch: `fix/011-phase2-infra-contract`, cut from `develop`.
- One commit. Message style is conventional commits — see
  `git log --oneline`, e.g. `fix(jobs): stop auditing when the job lease is lost`.
  Suggested: `test(infra): assert the hosted-OIDC compose contract`.
- Repo commit trailers are required. End the commit message with:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Replace the stale assertions

In `tests/test_phase2_infra.py`, replace the whole body of
`test_compose_enables_oidc_and_binds_public_services_to_loopback` (lines 31–39
in the excerpt above) with:

```python
def test_compose_enables_oidc_and_binds_public_services_to_loopback():
    services = _compose()["services"]
    environment = services["agentaudit"]["environment"]
    assert environment["AGENTAUDIT_AUTH_MODE"] == "oidc"
    # Every OIDC setting is supplied by the deployment rather than defaulted in
    # the image. The `${NAME:?...}` form makes Compose refuse to start when one
    # is missing, which is what stops a half-configured stack from coming up
    # with a silently wrong issuer or audience.
    for name in (
        "AGENTAUDIT_OIDC_ISSUER",
        "AGENTAUDIT_OIDC_JWKS_URL",
        "AGENTAUDIT_OIDC_TOKEN_URL",
        "AGENTAUDIT_OIDC_AUTH_URL",
        "AGENTAUDIT_OIDC_AUDIENCE",
        "AGENTAUDIT_OIDC_CLIENT_ID",
        "AGENTAUDIT_OIDC_REDIRECT_URI",
    ):
        assert environment[name].startswith(f"${{{name}:?")
    # Secure cookies are the default; only an explicit override relaxes them.
    assert (
        environment["AGENTAUDIT_SESSION_COOKIE_SECURE"]
        == "${AGENTAUDIT_SESSION_COOKIE_SECURE:-1}"
    )
    # TLS terminates at the reverse proxy, so nothing binds beyond loopback.
    assert services["agentaudit"]["ports"] == ["127.0.0.1:8000:8000"]
    assert services["keycloak"]["ports"] == ["127.0.0.1:8080:8080"]
    # The app no longer waits on a local IdP -- the provider is hosted. What it
    # must still wait for is the migration job.
    assert (
        services["agentaudit"]["depends_on"]["migrate"]["condition"]
        == "service_completed_successfully"
    )
```

Notes on details that matter:

- `f"${{{name}:?"` renders as `${AGENTAUDIT_OIDC_ISSUER:?` — the doubled braces
  are f-string escaping, not a typo. Do not "simplify" them.
- Keep the `keycloak` ports assertion. Those services still exist in compose;
  removing the assertion is a separate decision (see Maintenance notes).
- The function name stays the same. It still describes what the test does.

**Verify**: `python -m pytest tests/test_phase2_infra.py -k oidc` → `1 passed`

### Step 2: Confirm the whole file and the linters

**Verify**:

- `python -m pytest tests/test_phase2_infra.py` → `5 passed`
- `python -m ruff check tests/test_phase2_infra.py` → `All checks passed!`
- `python -m ruff format --check tests/test_phase2_infra.py` → exit 0, no
  files listed as needing reformatting. If it reports the file would be
  reformatted, run `python -m ruff format tests/test_phase2_infra.py` and
  re-run the check.

### Step 3: Confirm the suite is green

**Verify**: `python -m pytest` → `980 passed`, `0 failed`. Takes roughly six
minutes; most of it is process spawn, which is expected.

If any test *other* than the one you touched fails, that is a STOP condition —
it means something drifted between this plan and your checkout.

## Test plan

No new test functions. This plan repairs one existing test rather than adding
coverage, and the repaired assertions are strictly stronger than the ones they
replace: seven required-from-env settings and a cookie-security default, where
before there were two hardcoded literals.

Verification is the existing suite: `python -m pytest tests/test_phase2_infra.py`
→ 5 passed, then the full `python -m pytest` → 980 passed.

To confirm the new assertions genuinely bite rather than passing vacuously,
temporarily change one expected value (for example, assert
`AGENTAUDIT_OIDC_ISSUER` starts with `${WRONG:?`), re-run, and check it fails.
**Revert that experiment before committing** — `git diff` must show only the
intended change.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest tests/test_phase2_infra.py` exits 0 with `5 passed`
- [ ] `python -m pytest` exits 0 with `980 passed`, `0 failed`
- [ ] `python -m ruff check tests/test_phase2_infra.py` exits 0
- [ ] `python -m ruff format --check tests/test_phase2_infra.py` exits 0
- [ ] `git status --porcelain` lists **only** `tests/test_phase2_infra.py`
- [ ] `git diff -- infra/docker-compose.yml` is empty
- [ ] `grep -n "agentaudit-api\|keycloak:8080" tests/test_phase2_infra.py`
      returns no matches
- [ ] `plans/README.md` status row for 011 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows `infra/docker-compose.yml` changed since `9a27225`, or
  the excerpt at `tests/test_phase2_infra.py:31-39` does not match what you
  find.
- The full suite fails on any test other than the one in scope.
- Satisfying the test appears to require editing `infra/docker-compose.yml`.
  The compose file is the source of truth here; the test is what is wrong.
- The `keycloak` or `keycloak-db` services are absent from
  `infra/docker-compose.yml` — someone has removed the legacy stack ahead of
  you, and the two `keycloak` assertions in this plan are then wrong. Report
  rather than guessing at a replacement.
- `python -m pytest` reports a total other than 980 tests. The count in this
  plan is from a verified local run at `9a27225`; a different total means the
  suite drifted and the expected results here are unreliable.

## Maintenance notes

For whoever owns this next:

- **This test file still encodes the local Keycloak stack in two places.**
  `test_compose_requires_secrets_instead_of_shipping_defaults`
  (`tests/test_phase2_infra.py:42`) asserts five `KEYCLOAK_*` /
  `AGENTAUDIT_CI_ACME_SECRET` / `AGENTAUDIT_DEMO_USER_PASSWORD` secrets are
  required, and `test_realm_uses_code_pkce_and_client_credentials_only`
  (`:54`) reads `infra/keycloak/agentaudit-realm.json`. Both pass today. Both
  will break the moment anyone deletes the Keycloak services from compose —
  which is an open recommendation, since the app now targets a hosted provider
  and those five secrets are still hard-required (`${NAME:?}`) just to run
  `docker compose up`. That is a separate maintainer decision, deliberately not
  bundled here.
- **What a reviewer should scrutinize**: that the `${NAME:?` prefix assertions
  really are checking the fail-fast form and not merely that the value is a
  non-empty string. The `:?` is the load-bearing character.
- The `Complexity` CI job is red for an unrelated reason and is not fixed by
  this plan. `required` will stay red until plan 012 also lands. Both are
  needed before a green build appears.
