# Plan 006: Return the test suite to green (3 independent defects)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.

> **Drift check (run first)**:
> `git diff --stat 5959852..HEAD -- backend/agentaudit/reports/md.py agentaudit/config/treasury-http.yaml tests/test_web.py tests/test_reports.py tests/test_config.py`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `5959852`, 2026-08-29

## Why this matters

`python -m pytest` on `develop` is currently **4 failed, 951 passed**. Two of
the four failures are live product defects, not stale tests:

1. `reports/md.py:_timeline_block` never returns its accumulated list, so
   `agentaudit report --format md` raises `TypeError` for any run containing a
   failing multi-turn test. Markdown is the default report format — the
   product's primary output crashes on exactly the runs users care about.
2. The reference HTTP target config lost its `{{ input }}` placeholder, so the
   HTTP agent POSTs the literal string `"input"` as the request body for every
   test instead of the test prompt.

The third cause is genuinely stale: two new jailbreak packs grew the treasury
pack from 6 tests to 9, and two `test_web.py` assertions still hardcode 6.

These must be fixed before plan 007 turns CI on. Enabling CI against a red
suite would immediately block every PR, which is why this plan comes first.

## Current state

### Defect A — missing `return` in `_timeline_block`

- `backend/agentaudit/reports/md.py` — Markdown report renderer.

Excerpt (`backend/agentaudit/reports/md.py:40-47`, verified at `5959852`):

```python
def _timeline_block(result) -> list[str]:
    """A failing multi-turn test's timeline, indented as a fenced code block."""
    timeline = window_timeline(build_timeline(result))
    if len(timeline["turns"]) < 2:
        return []
    lines = ["", "  Timeline (turn where the failure first appears is marked):", "", "  ```"]
    lines.extend(f"  {line}" for line in timeline_lines(timeline))
    lines.append("  ```")
def _trial_lines(results) -> list[str]:
```

The function builds `lines` and then falls off the end, implicitly returning
`None`. Note there is also **no blank line** between the end of
`_timeline_block` and `def _trial_lines` — the two-blank-line separator ruff
expects is missing too, which is a second symptom of the same truncated edit.

Its two call sites both do `lines.extend(...)` on the result
(`backend/agentaudit/reports/md.py:84` and `:89`), so a `None` return raises
`TypeError: 'NoneType' object is not iterable`. The early `return []` at line
44 is why this only fires when a result actually has 2+ turns.

The declared return type is already `list[str]`; the fix is to honor it.

### Defect B — deleted `{{ input }}` placeholder

- `agentaudit/config/treasury-http.yaml` — sample HTTP target config.
- `backend/agentaudit/core/agent.py` — defines and substitutes the placeholder.

Excerpt (`backend/agentaudit/core/agent.py:18` and `:74-80`, verified at
`5959852`):

```python
_INPUT_PLACEHOLDER = "{{ input }}"

def _render_template(template: Any, input: str | dict) -> Any:
    if isinstance(template, str):
        if template == _INPUT_PLACEHOLDER:
            return input
        if _INPUT_PLACEHOLDER in template:
            return template.replace(_INPUT_PLACEHOLDER, str(input))
        return template
```

Excerpt (`agentaudit/config/treasury-http.yaml:16-20`, verified at `5959852`):

```yaml
  request:
    json:
      input: "input"
  response:
    text_path: "$.text"
```

Commit `3b89e3e` ("Fixin the malformed input.") changed this line from
`input: "{{ input }}"` to `input: "input"`. The `{{ }}` form is not malformed —
it is this repo's own placeholder syntax, defined at `agent.py:18`.

**Corroborating evidence that `{{ input }}` is correct**: the sibling config
`agentaudit/config/demo-stub-http.yaml:9` still reads `input: "{{ input }}"`
and was not touched by that commit. It is the reference for the correct shape.

### Defect C — stale pack-size assertions

- `tests/test_web.py` — web integration tests.

Two assertions hardcode the treasury pack at 6 tests:

- `tests/test_web.py:1153` (in `test_post_runs_enqueues_without_executing`)
- `tests/test_web.py:1443` (in `test_post_runs_enqueues_against_a_registered_target`)

Both read:

```python
    assert len(store.get_pack_tests(DEFAULT_ORG, job.pack_id)) == 6
```

The treasury pack legitimately grew to 9 tests when
`agentaudit/packs/treasury/jailbreak_refined_pressure.yaml` and
`agentaudit/packs/treasury/jailbreak_sequential_decomposition.yaml` were added.
The production code is correct here; the assertions are stale.

### Repo conventions

100-char lines, ruff `E`/`F`/`I`/`B`/`UP`, four-space indent, type annotations
on function signatures, two blank lines between top-level defs. Comments
explain *why*, not *what*. Match the surrounding style in each file.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python -m pytest` | exit 0, `955 passed` |
| Report tests | `python -m pytest tests/test_reports.py -q` | all pass |
| Config tests | `python -m pytest tests/test_config.py -q` | all pass |
| Web tests | `python -m pytest tests/test_web.py -q` | all pass |
| Lint | `python -m ruff check .` | `All checks passed!` |
| Format check | `python -m ruff format --check .` | exit 0 |

**Windows note**: call pytest as a module (`python -m pytest`), never as the
`uv run ... pytest` console script — the trampoline fails to canonicalize the
script path on this platform.

## Scope

**In scope** (the only files you should modify):
- `backend/agentaudit/reports/md.py`
- `agentaudit/config/treasury-http.yaml`
- `tests/test_web.py`

**Out of scope** (do NOT touch, even though they look related):
- `agentaudit/config/demo-stub-http.yaml` — already correct; it is your
  reference for defect B, not a target.
- `backend/agentaudit/core/agent.py` — the placeholder constant and
  `_render_template` are correct. The config is what drifted, not the code.
- `backend/agentaudit/core/timeline.py` (`build_timeline`, `window_timeline`,
  `timeline_lines`) — all three work correctly; only `md.py`'s use of them is
  broken.
- `agentaudit/packs/treasury/*.yaml` — the two new jailbreak packs are
  legitimate content. Do NOT delete them to make the count return to 6.
- `backend/agentaudit/reports/html.py`, `json.py`, `junit.py` — their timeline
  tests pass; they are unaffected.

## Git workflow

- Branch: `fix/006-green-the-suite` (already created off `develop`).
- Commit style is conventional-commit-ish; recent examples from `git log`:
  `fix(spa): keep the previous view while refetching, drop dead aria-live`,
  `feat(jobs): let a run carry a caller-defined time limit`.
  Suggested: `fix(reports): return the timeline block instead of None`.
- One commit per defect (three commits) is preferred — they are unrelated.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm the four failures reproduce

Run the suite first so you can prove the delta afterwards.

```
python -m pytest -q
```

**Verify**: output ends with `4 failed, 951 passed`. The four names are:
`tests/test_config.py::test_load_http_target_interpolates_env`,
`tests/test_reports.py::test_markdown_report_renders_timeline_for_failing_multi_turn_test`,
`tests/test_web.py::test_post_runs_enqueues_without_executing`,
`tests/test_web.py::test_post_runs_enqueues_against_a_registered_target`.

If a different set of tests fails, treat it as a STOP condition.

### Step 2: Fix defect A — return the accumulated lines

In `backend/agentaudit/reports/md.py`, add the missing `return lines` at the
end of `_timeline_block`, and restore the two blank lines before
`def _trial_lines`. The function must end:

```python
    lines.append("  ```")
    return lines


def _trial_lines(results) -> list[str]:
```

Change nothing else in the function — the list contents are correct, only the
return is missing.

**Verify**:
```
python -m pytest tests/test_reports.py -q
```
→ all pass, including
`test_markdown_report_renders_timeline_for_failing_multi_turn_test`.

### Step 3: Fix defect B — restore the input placeholder

In `agentaudit/config/treasury-http.yaml`, change the request body line back to
the placeholder form so it matches `demo-stub-http.yaml:9`:

```yaml
  request:
    json:
      input: "{{ input }}"
```

The quoting matters: `"{{ input }}"` must be a quoted string with single spaces
inside the braces, byte-identical to `_INPUT_PLACEHOLDER` at `agent.py:18`.
Unquoted `{{ input }}` is a YAML flow-mapping and will not parse as a string.

**Verify**:
```
python -m pytest tests/test_config.py -q
```
→ all pass, including `test_load_http_target_interpolates_env`.

Then confirm the two sample configs agree:
```
grep -rn "input:" agentaudit/config/*.yaml
```
→ both `demo-stub-http.yaml` and `treasury-http.yaml` show `input: "{{ input }}"`.

### Step 4: Fix defect C — update the stale pack-size assertions

In `tests/test_web.py`, update **both** assertions (lines 1153 and 1443) from
`== 6` to `== 9`.

Do not parameterize, extract a constant, or otherwise restructure these tests —
the change is the number only. Both lines read identically before and after.

**Verify**:
```
python -m pytest tests/test_web.py -q
```
→ all pass.

### Step 5: Full verification

```
python -m pytest -q
python -m ruff check .
```

**Verify**: `955 passed`, exit 0; ruff prints `All checks passed!`.

## Test plan

No new test files. Each defect already has a failing test that becomes the
regression guard:

- Defect A → `tests/test_reports.py::test_markdown_report_renders_timeline_for_failing_multi_turn_test`
  (asserts `"Turn 0: plant poison"` and
  `"Turn 1: cash it in <-- first divergence"` appear in the rendered Markdown).
- Defect B → `tests/test_config.py::test_load_http_target_interpolates_env`
  (asserts `cfg.agent.request["json"]["input"] == "{{ input }}"`).
- Defect C → the two `tests/test_web.py` enqueue tests.

**Do not write new tests for these three.** The existing coverage is exactly
right and already pinned the bugs; adding more would be duplicate coverage. If
you believe a gap exists, note it in your report rather than filling it here —
that is a scope decision for the maintainer.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest` exits 0 and reports `955 passed`, 0 failed
- [ ] `python -m ruff check .` exits 0 with `All checks passed!`
- [ ] `grep -n "return lines" backend/agentaudit/reports/md.py` matches inside
      `_timeline_block`
- [ ] `grep -c '"{{ input }}"' agentaudit/config/treasury-http.yaml` returns `1`
- [ ] `grep -c "== 6" tests/test_web.py` returns `0` for the pack-size lines
      (verify by eye that lines 1153 and 1443 now read `== 9`)
- [ ] `git status --short` shows exactly three modified files and no others
- [ ] `plans/README.md` status row for 006 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 shows a different set of failing tests than the four named — the
  codebase has drifted since this plan was written.
- After step 2, `tests/test_reports.py` still fails: the defect may be in
  `core/timeline.py` rather than `md.py`, which is out of scope for this plan.
- Restoring `{{ input }}` makes a *different* test fail — that would mean
  something downstream adapted to the broken value, and the blast radius is
  larger than this plan assumes.
- The treasury pack does not contain exactly 9 tests
  (`ls agentaudit/packs/treasury/*.yaml | wc -l` to sanity-check) — pick the
  real number rather than blindly writing 9, and say so in your report.
- Any fix appears to require touching a file on the out-of-scope list.

## Maintenance notes

For whoever owns this next:

- **Defect A is a class, not an instance.** Ruff's selected rule set
  (`E`,`F`,`I`,`B`,`UP`) does **not** flag a function annotated `-> list[str]`
  that falls off the end returning `None`. A typechecker would have caught this
  at author time. That is prior audit finding #15 (no typechecker configured),
  and this bug is the concrete argument for it. Worth revisiting.
- **Defect B is a docs/naming problem underneath.** Someone read `{{ input }}`
  as malformed Jinja and "fixed" it. Consider a one-line comment in
  `treasury-http.yaml` next to the placeholder pointing at
  `core/agent.py:_INPUT_PLACEHOLDER`, so the next reader does not repeat it.
  Deferred out of this plan deliberately — it is a judgment call about comment
  density, and this plan should stay a pure bug fix.
- **Defect C will recur** every time a pack gains a test. A reviewer should
  push back on any new hardcoded pack-size assertion; asserting on a specific
  test id present in the pack is the more durable shape.
- Reviewer should scrutinize: that `treasury-http.yaml` quoting is exactly
  `"{{ input }}"`, and that no pack YAML was deleted to satisfy defect C.
