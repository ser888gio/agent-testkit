# Plan 001: Reject backslash-form open redirect in login `next` url

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat e4cfe48..HEAD -- frontend/agentaudit/web/auth.py tests/test_auth.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `e4cfe48`, 2026-08-26

## Why this matters

The OIDC login flow accepts a `next` query parameter as the post-login
destination after validating it looks like a local path. The validation misses
backslash URLs: `/\evil.com` passes every check (`urlsplit("/\\evil.com")`
yields no scheme/netloc; the string starts with `/`; it does not start with
`//`), but browsers canonicalize `\` to `/` in the authority position, so the
user's browser navigates to `//evil.com`. An attacker can send a victim
`/login?next=/\evil.com` and, after the victim completes a legitimate Keycloak
sign-in, land them on an attacker-controlled page styled as the dashboard — a
phishing hop inheriting full IdP-flow trust. No legitimate `next` value
contains a backslash, so rejection costs nothing.

## Current state

- `frontend/agentaudit/web/auth.py` — auth helpers; contains `_safe_next_url`.
- `tests/test_auth.py` — auth tests; has an existing case asserting that an
  absolute URL is rejected (~line 204) which is the structural pattern to follow.

Excerpt of the current validator (`frontend/agentaudit/web/auth.py:252-257`,
verified at commit `e4cfe48`):

```python
def _safe_next_url(value: str | None) -> str:
    if not value:
        return "/"
    parsed = parse.urlsplit(value)
    is_local_path = not parsed.scheme and not parsed.netloc and value.startswith("/")
    return value if is_local_path and not value.startswith("//") else "/"
```

The stored value is returned to the SPA post-login and redirected to via
`RedirectResponse(destination, 303)` in `frontend/agentaudit/web/app.py`
(login-completion handler). Repo conventions: 100-char lines, ruff E/F/I/B/UP,
type annotations required, four-space indent. Match the existing terse
validator style above.

## Commands you will need

| Purpose   | Command                                              | Expected on success |
|-----------|------------------------------------------------------|---------------------|
| Tests     | `uv run --extra dev pytest tests/test_auth.py`       | all pass            |
| Security suite | `uv run --extra dev pytest tests/test_security_p0.py` | all pass (release blocker must stay green) |
| Lint      | `uv run ruff check frontend/agentaudit/web/auth.py tests/test_auth.py` | exit 0 |

## Scope

**In scope** (the only files you should modify):
- `frontend/agentaudit/web/auth.py` (the `_safe_next_url` function only)
- `tests/test_auth.py` (add cases)

**Out of scope** (do NOT touch):
- `frontend/agentaudit/web/app.py` — redirect handling is fine once validation rejects the input.
- Any other auth behavior (session creation, CSRF, cookie flags).

## Git workflow

- Branch: `advisor/001-next-url-backslash`
- Commit style: short imperative subject, optionally task-ID prefixed (repo
  history example: `T18: fix SPA serving and session loading`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Harden `_safe_next_url` against backslashes

In `frontend/agentaudit/web/auth.py`, change the local-path check to also
reject any value containing `"\"`. Target shape:

```python
def _safe_next_url(value: str | None) -> str:
    if not value:
        return "/"
    if "\\" in value:
        return "/"
    parsed = parse.urlsplit(value)
    is_local_path = not parsed.scheme and not parsed.netloc and value.startswith("/")
    return value if is_local_path and not value.startswith("//") else "/"
```

(Rejecting early is clearer than normalizing; there is no legitimate
backslash-bearing local path.)

**Verify**: `uv run python -c "from agentaudit.web.auth import _safe_next_url as f; assert f('/\\evil.com') == '/' and f('/runs') == '/runs' and f('https://evil.com') == '/' and print('ok')"` → prints `ok`

### Step 2: Add regression tests

In `tests/test_auth.py`, next to the existing absolute-URL-rejection case
(~line 204), add cases asserting fallback-to-`/` for:
1. `next="/\evil.com"` (the bug being fixed)
2. `next="\\evil.com"` (leading backslash variant)
3. `next="/safe/path?x=1"` still accepted (guard against over-blocking)

Follow the existing test's client/request pattern exactly.

**Verify**: `uv run --extra dev pytest tests/test_auth.py -k next` → all pass including the new cases

## Test plan

- New tests listed in Step 2, in `tests/test_auth.py`, modeled on the
  existing `next`-url rejection test.
- Verification: `uv run --extra dev pytest tests/test_auth.py` → all pass;
  then `uv run --extra dev pytest tests/test_web.py tests/test_security_p0.py`
  → all pass (auth changes must not disturb the route-walk or security suite).

## Done criteria

- [ ] `uv run python -c "..."` assertion from Step 1 exits 0
- [ ] `uv run --extra dev pytest tests/test_auth.py` exits 0 with ≥3 new tests
- [ ] Full security suite green: `uv run --extra dev pytest tests/test_security_p0.py`
- [ ] `uv run ruff check frontend/agentaudit/web/auth.py tests/test_auth.py` exits 0
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:
- The code at `auth.py:252-257` doesn't match the excerpt (drift since planning).
- Adding the backslash rejection breaks any *existing* test (would mean a
  legit consumer relies on backslash paths — needs human judgment).
- The fix appears to require touching out-of-scope files.

## Maintenance notes

- Reviewer should scrutinize: no other `next`-like parameter exists elsewhere
  (grep for `next_url`) without the same guard.
- Future: if multi-segment Windows-style paths are ever legitimate inputs,
  revisit — today none are.
