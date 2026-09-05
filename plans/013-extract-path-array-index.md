# Plan 013: Teach `_extract_path` array indexing so OpenAI-shaped agents can be registered

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7cb6196..HEAD -- backend/agentaudit/core/agent.py backend/agentaudit/core/discovery.py tests/test_agent.py tests/test_discovery.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `7cb6196`, 2026-09-04

## Why this matters

`agentaudit` can auto-detect an unknown HTTP agent's request/response shape by
trying a short list of candidate shapes (`CANDIDATE_SHAPES`). The last and most
important candidate is the OpenAI chat-completions shape, whose response path is
`$.choices[0].message.content`. But the path evaluator, `_extract_path`, splits
only on `.` and only indexes into dicts — it has no concept of `[0]`. So the
segment `choices[0]` is looked up as a literal dict key, is never found, and the
candidate can never match.

The practical cost: an OpenAI-compatible endpoint — the single most common agent
shape there is — can never be registered through the dashboard. Registration
fails with `ShapeUnknown`, which becomes a `PermanentJobError`, and the error
text tells the user to "register it with a YAML config instead" — but a
hand-written YAML config using that same `text_path` fails identically, because
it goes through the same evaluator. The feature that exists so common cases need
no config is broken for the most common case.

This is verified, not inferred. At commit `7cb6196`:

```
>>> _extract_path({"choices": [{"message": {"content": "hi"}}]}, "$.choices[0].message.content")
(False, None)
>>> _extract_path({"text": "hi"}, "$.text")
(True, 'hi')
```

## Current state

Files involved:

- `backend/agentaudit/core/agent.py` — defines `_extract_path`, the single
  evaluator for every response `text_path` in the product. This is the file you
  will change.
- `backend/agentaudit/core/discovery.py` — defines `CANDIDATE_SHAPES`, the list
  of shapes `detect_shape` tries. Read-only for this plan; you are fixing the
  evaluator so its existing last entry can work.
- `tests/test_agent.py` — unit tests for the agent module. New evaluator tests go here.
- `tests/test_discovery.py` — tests for shape detection. One new test goes here.

`backend/agentaudit/core/agent.py:90-101` — the whole function as it exists today:

```python
def _extract_path(body: Any, path: str) -> tuple[bool, Any]:
    parts = path.lstrip("$").lstrip(".").split(".") if path.strip("$") else []
    current = body
    for part in parts:
        if not part:
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current
```

Note the contract: it returns `(found, value)`. A miss is `(False, None)` — it
never raises. Every caller depends on that; preserve it exactly.

`backend/agentaudit/core/discovery.py:248-259` — the candidate list, unchanged
by this plan:

```python
CANDIDATE_SHAPES: list[tuple[dict, str]] = [
    ({"json": {"input": "{{ input }}"}}, "$.text"),
    ({"json": {"input": "{{ input }}"}}, "$.output"),
    ({"json": {"prompt": "{{ input }}"}}, "$.text"),
    ({"json": {"prompt": "{{ input }}"}}, "$.completion"),
    ({"json": {"message": "{{ input }}"}}, "$.reply"),
    (
        {"json": {"messages": [{"role": "user", "content": "{{ input }}"}]}},
        "$.choices[0].message.content",
    ),
]
```

Repo conventions that apply here:

- Python 3.10+, `from __future__ import annotations` at the top of most modules.
- Line length 100 (`pyproject.toml` `[tool.ruff]`). Ruff lint selects
  `E, F, I, B, UP` and the repo is currently green — do not introduce a violation.
- Comments in this repo explain *why*, not *what*, and are written in full
  sentences. Match that register; see the comment block at
  `backend/agentaudit/core/discovery.py:240-247` for the house style.
- Tests are plain pytest functions named `test_<behavior>`, no classes, no
  fixtures beyond `tmp_path`/`monkeypatch`. See `tests/test_agent.py:8-25` for
  the structural pattern to follow.

## Commands you will need

| Purpose            | Command                                              | Expected on success        |
|--------------------|------------------------------------------------------|----------------------------|
| Targeted tests     | `python -m pytest tests/test_agent.py`                | all pass                   |
| Discovery tests    | `python -m pytest tests/test_discovery.py`            | all pass                   |
| HTTP agent tests   | `python -m pytest tests/test_http_agent.py`           | all pass                   |
| Lint               | `python -m ruff check .`                              | `All checks passed!`       |
| Full suite         | `python -m pytest`                                    | `1066 passed` (or more)    |

**Windows note**: call pytest and ruff as modules (`python -m pytest`), never as
console scripts. `uv run ... pytest` fails on Windows with
`uv trampoline failed to canonicalize script path`. This is a known environment
issue documented in `CLAUDE.md`.

The full suite takes about 11 minutes on Windows. Use the targeted commands
while iterating; run the full suite once before declaring done.

## Scope

**In scope** (the only files you should modify):

- `backend/agentaudit/core/agent.py` — `_extract_path` only
- `tests/test_agent.py` — add tests
- `tests/test_discovery.py` — add one test

**Out of scope** (do NOT touch, even though they look related):

- `backend/agentaudit/core/discovery.py` — `CANDIDATE_SHAPES` is already
  correct. The bug is in the evaluator, not the candidate list. Do not add,
  remove or reorder candidates.
- `_render_template` (`agent.py:78-87`) — request-side templating, a different
  direction of travel. Unrelated.
- Any change to the `(found, value)` return contract of `_extract_path`.
- Do not introduce a JSONPath dependency. This is a deliberately tiny path
  grammar; keep it dependency-free.

## Git workflow

- Branch off `develop`: `git checkout -b fix/013-extract-path-array-index develop`
- The repo uses conventional-commit subjects. Example from `git log`:
  `fix: apply the egress policy to CLI-supplied endpoints`
- Commit message must end with the repo trailers:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add array indexing to `_extract_path`

Rewrite `_extract_path` in `backend/agentaudit/core/agent.py` so each dot
segment may carry one or more trailing `[n]` subscripts.

Required behavior:

- `"$.text"` → dict key `text` (unchanged from today).
- `"$.choices[0].message.content"` → dict key `choices`, then list index `0`,
  then dict keys `message`, `content`.
- Multiple subscripts on one segment (`"$.a[0][1]"`) must work.
- A leading-subscript path (`"$[0].text"`) must work — the segment before the
  bracket is empty, which today is skipped by the `if not part: continue` guard.
- Negative indices are **not** supported: treat `[-1]` as a miss, returning
  `(False, None)`. Rationale: a response path is a contract with a partner
  endpoint, and silently accepting Python's negative-index semantics would make
  a typo look like a working path.
- Out-of-range index → `(False, None)`, never `IndexError`.
- Indexing a non-list (e.g. a dict or a string) → `(False, None)`.
- A malformed subscript (`"a[x]"`, `"a["`, `"a[]"`) → `(False, None)`, never an
  exception.
- The function must still never raise for any input.

A shape that satisfies this (you may implement it differently as long as every
bullet above holds and the tests in Step 2 pass):

```python
_SUBSCRIPT = re.compile(r"\[(\d+)\]")


def _extract_path(body: Any, path: str) -> tuple[bool, Any]:
    """Resolve a `$.a.b[0].c` path against a decoded response body.

    Returns `(found, value)` and never raises: a missing key, an out-of-range
    index, or a malformed subscript are all reported as `(False, None)` so a
    partner endpoint that answers in an unexpected shape becomes evidence
    rather than a crash. Only non-negative literal indices are accepted --
    a response path is a contract, and accepting `[-1]` would let a typo
    resolve to a real element.
    """
    parts = path.lstrip("$").lstrip(".").split(".") if path.strip("$") else []
    current = body
    for part in parts:
        name, _, subscripts = part.partition("[")
        if name:
            if not isinstance(current, dict) or name not in current:
                return False, None
            current = current[name]
        elif not subscripts:
            continue
        if subscripts:
            remainder = "[" + subscripts
            for match in _SUBSCRIPT.finditer(remainder):
                if not isinstance(current, list):
                    return False, None
                index = int(match.group(1))
                if index >= len(current):
                    return False, None
                current = current[index]
            if _SUBSCRIPT.sub("", remainder):
                # Something in the brackets was not a plain integer.
                return False, None
    return True, current
```

`re` is already imported in `agent.py`; confirm before adding an import, and if
it is not, add it in the correct isort position (ruff will tell you).

**Verify**:

```
python -c "import sys; sys.path.insert(0,'backend'); from agentaudit.core.agent import _extract_path as e; print(e({'choices':[{'message':{'content':'hi'}}]}, '$.choices[0].message.content')); print(e({'text':'hi'}, '$.text')); print(e({'choices':[]}, '$.choices[0].message.content')); print(e({'a':{'b':1}}, '$.a[0]'))"
```

→ expected output, in order:

```
(True, 'hi')
(True, 'hi')
(False, None)
(False, None)
```

### Step 2: Add evaluator unit tests

Add to `tests/test_agent.py`, following the existing flat `def test_...` style
(see `tests/test_agent.py:8-25`). Import `_extract_path` alongside the existing
imports from `agentaudit.core.agent`.

Cover exactly these cases, one assertion-focused test each (or a single
parametrized test — `pytest.mark.parametrize` is acceptable and already used
elsewhere in the suite):

1. `"$.text"` against `{"text": "hi"}` → `(True, "hi")` (regression: plain paths
   still work).
2. `"$.choices[0].message.content"` against a well-formed OpenAI body →
   `(True, "hi")` — **this is the bug this plan fixes**.
3. `"$.choices[0].message.content"` against `{"choices": []}` → `(False, None)`.
4. `"$.choices[5].message.content"` against a one-element list → `(False, None)`.
5. `"$.a[0]"` against `{"a": {"b": 1}}` (subscript on a dict) → `(False, None)`.
6. `"$.a[-1]"` against `{"a": [1, 2]}` → `(False, None)` (negatives refused).
7. `"$.a[x]"` and `"$.a["` against `{"a": [1, 2]}` → `(False, None)`, and the
   call does not raise.
8. `"$[0].text"` against `[{"text": "hi"}]` → `(True, "hi")`.
9. `"$.a[0][1]"` against `{"a": [[0, "hi"]]}` → `(True, "hi")`.

**Verify**: `python -m pytest tests/test_agent.py` → all pass, including your
9 new cases.

### Step 3: Add a discovery test proving the OpenAI candidate is now reachable

Add one test to `tests/test_discovery.py` asserting that `detect_shape` selects
the OpenAI candidate when the stub agent answers in that shape.

Use the existing helpers in that file — `tests/test_discovery.py:1-40` shows the
import block and the `_target(...)` helper — and model the new test on the
existing `detect_shape` tests already in that file (search for `detect_shape`).
The assertion must be that the selected `text_path` equals
`"$.choices[0].message.content"`.

Read the surrounding tests before writing this one: `detect_shape`'s exact
signature and how the suite stubs an HTTP responder are established there, and
you must match that pattern rather than inventing a new stub.

**Verify**: `python -m pytest tests/test_discovery.py` → all pass, including the
new test.

### Step 4: Full validation

**Verify**:

- `python -m ruff check .` → `All checks passed!`
- `python -m pytest` → `1066 passed` or more, `0 failed`

## Test plan

- **New tests in `tests/test_agent.py`**: the nine cases listed in Step 2 —
  the plain-path regression, the OpenAI happy path, empty list, out-of-range,
  subscript-on-non-list, negative index, two malformed subscripts, leading
  subscript, and chained subscripts.
- **New test in `tests/test_discovery.py`**: `detect_shape` selects the OpenAI
  candidate for an agent answering in that shape.
- **Structural pattern**: `tests/test_agent.py:8-25` for the evaluator tests;
  the existing `detect_shape` tests in `tests/test_discovery.py` for the
  discovery test.
- **Verification**: `python -m pytest` → all pass, including 10 new tests.

## Done criteria

ALL must hold:

- [ ] `python -m ruff check .` exits 0 with `All checks passed!`
- [ ] `python -m pytest` exits 0 with at least `1066 passed`, `0 failed`
- [ ] The Step 1 verify command prints `(True, 'hi')`, `(True, 'hi')`,
      `(False, None)`, `(False, None)` in that order
- [ ] 10 new tests exist across `tests/test_agent.py` and `tests/test_discovery.py`
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/README.md` status row for 013 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `_extract_path` at `backend/agentaudit/core/agent.py:90-101` does not match
  the excerpt in "Current state" — the codebase has drifted.
- `CANDIDATE_SHAPES` no longer contains the `$.choices[0].message.content`
  entry — someone removed the candidate instead of fixing the evaluator, and
  this plan's premise is gone.
- Making the discovery test pass appears to require changing
  `backend/agentaudit/core/discovery.py`. It should not. Report what you found.
- Any currently-passing test starts failing and the cause is not an obvious
  slip in your own edit. In particular, if an existing test asserts that a
  bracketed path is *not* found, stop — that would mean the current behavior is
  load-bearing somewhere and this plan's premise is wrong.
- The full suite fails on a test unrelated to the agent or discovery modules
  twice in a row. That is pre-existing breakage, not yours; report it.

## Maintenance notes

- `_extract_path` is now the closest thing this repo has to a JSONPath
  evaluator. Resist growing it further — wildcards, filters and slices are the
  point at which a real library beats hand-rolled code, and the grammar
  deliberately stops at "dot segments plus non-negative integer subscripts".
  If a partner needs more, that is the moment to reconsider, not to add a
  seventh special case.
- Turning this on changes `detect_shape`'s behavior for OpenAI-compatible
  endpoints: shapes that previously fell through to `ShapeUnknown` will now
  match. If any golden/plan-comparison test encodes the old outcome, it will
  need updating — that is an expected consequence, not a regression.
- A reviewer should scrutinize the malformed-subscript and negative-index
  branches specifically. Those are the cases where a permissive implementation
  turns a partner's typo into a silently wrong extraction.
- Deferred out of this plan: `discovery.py` also mis-parses tool self-reports by
  calling `str()` on a dict response (`discovery.py:225`), so
  `parse_tool_names` always returns `[]`. That is a separate defect in the same
  module and is not part of this change.
