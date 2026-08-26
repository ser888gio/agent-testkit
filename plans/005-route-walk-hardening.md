# Plan 005: Fail loudly on unrecognized path params in the route-table auth walk

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**: `git diff --stat e4cfe48..HEAD -- tests/test_web.py`
> On any mismatch with "Current state" below, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `e4cfe48`, 2026-08-26

## Why this matters

The repo's core web-security guarantee — "every application route takes a
Principal" — is enforced by `test_every_route_requires_a_token`, which walks
the FastAPI route table, fills path parameters, and asserts each request is
rejected without a token. The substitution list is HARDCODED: a future route
introducing any new parameter name (e.g. `{pack_id}`) gets requested with the
literal brace text, fails routing with 404 before dependencies execute, and is
silently counted as protected. The guarantee degrades exactly when a new
route shape appears — the highest-risk moment for an auth gap. Additionally,
methods outside GET/POST are silently skipped.

## Current state

Verified excerpt at commit `e4cfe48` — `tests/test_web.py:683-703`:

```python
def _concrete_paths() -> list[tuple[str, str]]:
    """Every app route, with path params filled in. Static mounts excluded."""
    from agentaudit.web.app import app

    out = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if (
            not path.startswith("/")
            or path.startswith("/static")
            or path.startswith("/assets")
            or path in {"/login", "/auth/callback", "/logout"}
        ):
            continue
        for method in methods & {"GET", "POST"}:
            filled = (
                path.replace("{run_id}", "some-run")
                .replace("{test_id}", "some-test")
                .replace("{job_id}", "some-job")
                .replace("{fmt}", "md")
                .replace("{artifact_id}", "some-artifact")
                .replace("{agent_id:path}", "some-agent")
                .replace("{full_path:path}", "some-shell-path")
            )
            out.append((method, filled))
    return out
```

Conventions (`tests/CLAUDE.md`): one test concern per test, failure messages
actionable. The consuming test (~line 723) treats "not unprotected" as pass.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Web tests | `uv run --extra dev pytest tests/test_web.py` | all pass |
| Lint      | `uv run ruff check tests/test_web.py` | exit 0 |

## Scope

**In scope**:
- `tests/test_web.py` (only `_concrete_paths` and/or the walk test)

**Out of scope**:
- Application code — this is a test-infrastructure hardening only.
- Changing which paths are excluded from the walk.

## Git workflow

- Branch: `advisor/005-route-walk-hardening`
- Commit style: short imperative subject.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Substitute path params generically and fail on leftovers

Replace the hardcoded `.replace(...)` chain with regex-based substitution plus
an assertion:

```python
import re

_PLACEHOLDER_VALUES = {
    "run_id": "some-run",
    "test_id": "some-test",
    "job_id": "some-job",
    "fmt": "md",
    "artifact_id": "some-artifact",
    "agent_id": "some-agent",
    "full_path": "some-shell-path",
}


def _fill(path: str) -> str:
    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        value = _PLACEHOLDER_VALUES.get(name)
        assert value is not None, (
            f"route parameter {{{name}}} has no substitution entry in "
            "_PLACEHOLDER_VALUES; add one so the auth walk actually exercises "
            f"this route ({path})"
        )
        return value

    filled = re.sub(r"\{(\w+)(?::path)?\}", sub, path)
    assert "{" not in filled, f"unsubstituted placeholder remains in {filled}"
    return filled
```

Call `_fill(path)` where the replace-chain was. The assertion message tells
the future contributor exactly what to do — the walk now fails loudly instead
of silently skipping.

**Verify**: `uv run --extra dev pytest tests/test_web.py -k every_route` → still passes (all current routes covered)

### Step 2: Prove the guard works (self-test)

Temporarily add a fake route param: in a scratch checkout step (do NOT
commit), edit one route in `frontend/agentaudit/web/api.py` to rename a param
(e.g. `{run_id}` → `{widget_id}`), run the walk, and confirm it FAILS with
your message. Revert immediately.

**Verify**: walk fails with the actionable message → then revert → walk green again

### Step 3: Cover non-GET/POST methods

Change `methods & {"GET", "POST"}` to iterate ALL route methods (e.g.
`for method in sorted(methods)`), since a future DELETE/PATCH route must also
be walked. Confirm the current route table contains no such methods yet
(the walk result count should be unchanged today).

**Verify**: `uv run --extra dev pytest tests/test_web.py -k every_route` → passes with same number of walked routes as before (compare output counts)

## Test plan

- No new test files; the existing walk becomes strict. Step 2's manual probe
  is the proof the hardening bites (do not commit the probe).
- Verification: `uv run --extra dev pytest tests/test_web.py` → all pass.

## Done criteria

- [ ] Walk fails loudly when a route introduces an unknown param (Step 2 probe demonstrated)
- [ ] `uv run --extra dev pytest tests/test_web.py` exits 0 after revert
- [ ] All route methods walked, not just GET/POST
- [ ] `uv run ruff check tests/test_web.py` exits 0
- [ ] Only `tests/test_web.py` modified (`git status`); probe edits reverted
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:
- `_concrete_paths` doesn't match the excerpt (drift).
- Making methods exhaustive causes currently-skipped routes to fail the walk
  (means a real auth gap may already exist — report, do not "fix" by
  excluding routes).
- The walk starts failing on static/mounted routes after generic substitution.

## Maintenance notes

- Reviewer should scrutinize: exclusion set `{"/login", "/auth/callback", "/logout"}`
  unchanged; substitution values still produce routable URLs for every listed param.
- Future: if FastAPI version upgrade changes `{param:path}` syntax handling,
  revisit the regex.
