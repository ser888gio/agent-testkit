# Plan 014: Thread the run's `Redactor` into the attacker and judge models

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7cb6196..HEAD -- backend/agentaudit/core/runner.py backend/agentaudit/core/attacker.py backend/agentaudit/core/judge.py tests/test_attacker.py tests/test_judge.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `7cb6196`, 2026-09-04

## Why this matters

When an adaptive test runs with a model-driven attacker or judge configured, the
agent's transcript is POSTed to a third-party model API. Both `RefiningStrategy`
and `ModelJudge` redact that text before sending it — and both accept a
`redactor` constructor argument for exactly that purpose, with comments saying
that defaulting it would be "a silent evidence leak to a third party".

But the two builder functions that the runner actually calls,
`build_refining_strategy` and `build_judge`, do not expose that argument at all.
So the runner cannot pass one even though it is holding the right one, and both
objects fall back to `Redactor(RedactionConfig())` — built-in patterns only.

The redactor the runner holds is not the built-in one. `worker.py:203-208`
builds it with `literals = [*target.evidence.redact.literals, *secrets.values()]`
— the target's declared literals plus the **resolved credential values** for
that run. The comment there is explicit that this is the point: "A resolved
credential is a literal the redactor must mask even though it never appears in
the stored config."

Net effect: the one credential the system knows for certain is a secret, plus
every custom literal and pattern a partner declared, are the exact strings that
do **not** get masked before the transcript leaves the machine. The intent is
already written into the code in three comments; only the wiring is missing.

## Current state

Files involved:

- `backend/agentaudit/core/runner.py` — `_run_turns` builds the judge and
  strategy. It holds the run's `Redactor` but does not pass it. You will change
  this.
- `backend/agentaudit/core/attacker.py` — `RefiningStrategy.__init__` already
  takes `redactor`; `build_refining_strategy` does not forward one. You will
  change the builder.
- `backend/agentaudit/core/judge.py` — same shape: `ModelJudge.__init__` takes
  `redactor`, `build_judge` does not. You will change the builder.
- `tests/test_attacker.py`, `tests/test_judge.py` — where the new tests go.

`backend/agentaudit/core/runner.py:142-152` — the call site:

```python
    if test.adaptive is not None:
        # Both model-driven layers are opt-in and return None when
        # unconfigured, so the scripted ladder with its substring stop check
        # stays the default path for every offline run. The logs are passed in
        # rather than left to default so what they record survives the call.
        refinement_log = RefinementLog()
        judge_log = JudgeLog()
        judge = build_judge(log=judge_log)
        strategy = build_refining_strategy(
            test.input, test.adaptive, log=refinement_log, judge=judge
        ) or build_strategy(test.input, test.adaptive, judge)
```

`backend/agentaudit/core/attacker.py:278-289` — the attacker builder:

```python
def build_refining_strategy(
    goal: str,
    spec: AdaptiveSpec,
    model: AttackerModel | None = None,
    log: RefinementLog | None = None,
    judge: Judge | None = None,
) -> AttackStrategy | None:
    """A refining strategy, or None when refinement is off or unconfigured."""
    attacker = model if model is not None else build_attacker(spec)
    if attacker is None:
        return None
    return RefiningStrategy(goal, spec, attacker, log=log, judge=judge)
```

`backend/agentaudit/core/attacker.py:211-218` — the constructor that already
accepts what the builder drops:

```python
    def __init__(
        self,
        goal: str,
        spec: AdaptiveSpec,
        model: AttackerModel,
        redactor: Redactor | None = None,
        log: RefinementLog | None = None,
        judge: Judge | None = None,
    ) -> None:
```

`backend/agentaudit/core/attacker.py:230-234` — the safe default it falls back to:

```python
        # Defaults to a builtins-on Redactor rather than None: the failure mode
        # of forgetting one here is leaking evidence to a third-party API, so
        # the default has to be the safe one even if the caller passes nothing.
        self.redactor = redactor if redactor is not None else Redactor(RedactionConfig())
```

`backend/agentaudit/core/judge.py:137-150` — the judge builder:

```python
def build_judge(log: JudgeLog | None = None) -> ModelJudge | None:
    """The configured judge, or None to keep using the substring check.
    ...
    """
    client = llm.build_client(llm.load_llm_config().judge, default_temperature=0.0)
    if client is None:
        return None
    return ModelJudge(client, log=log)
```

`backend/agentaudit/core/judge.py:85-96` — the constructor:

```python
    def __init__(
        self,
        model: AttackerModel,
        threshold: float = 0.7,
        redactor: Redactor | None = None,
        log: JudgeLog | None = None,
    ) -> None:
        self.model = model
        self.threshold = threshold
        # Same reasoning as RefiningStrategy: defaulting to None would make
        # "forgot to pass a redactor" a silent evidence leak to a third party.
        self.redactor = redactor if redactor is not None else Redactor(RedactionConfig())
```

Where the text is actually redacted before leaving:
`attacker.py:249` (`self.redactor.redact_text(r.text)` for each history entry)
and `judge.py:104` (`self.redactor.redact_text(response.text)`).

Repo conventions:

- Keyword-only-by-convention optional args: these builders take
  `name: Type | None = None` and forward with `name=name`. Match that.
- Do not reorder existing parameters — `build_refining_strategy`'s third
  positional is `model` and tests may pass it positionally.
- Comments explain *why*. See `attacker.py:230-232` for the register.
- Line length 100; ruff selects `E, F, I, B, UP` and is currently green.

## Commands you will need

| Purpose          | Command                                       | Expected on success     |
|------------------|-----------------------------------------------|-------------------------|
| Attacker tests   | `python -m pytest tests/test_attacker.py`      | all pass                |
| Judge tests      | `python -m pytest tests/test_judge.py`         | all pass                |
| Runner tests     | `python -m pytest tests/test_runner.py`        | all pass                |
| Lint             | `python -m ruff check .`                       | `All checks passed!`    |
| Full suite       | `python -m pytest`                             | `1066 passed` (or more) |

**Windows note**: call pytest and ruff as modules (`python -m pytest`), never as
console scripts — `uv run ... pytest` fails on Windows with
`uv trampoline failed to canonicalize script path`.

The full suite takes about 11 minutes. Use targeted commands while iterating.

## Scope

**In scope** (the only files you should modify):

- `backend/agentaudit/core/attacker.py` — `build_refining_strategy` only
- `backend/agentaudit/core/judge.py` — `build_judge` only
- `backend/agentaudit/core/runner.py` — the `_run_turns` call site only
- `tests/test_attacker.py` — add tests
- `tests/test_judge.py` — add tests

**Out of scope** (do NOT touch, even though they look related):

- `RefiningStrategy.__init__` and `ModelJudge.__init__` — they already do the
  right thing. Do not change their signatures or their safe defaults. In
  particular, **do not** make `redactor` required; the builtins-on default is a
  deliberate safety property and removing it would turn a future missed call
  site into a crash instead of a degraded-but-safe path.
- `backend/agentaudit/core/llm.py` and `build_attacker` — model construction and
  configuration are a separate concern, addressed by plan 015.
- `backend/agentaudit/core/redaction.py` — the redactor's own pattern
  vocabulary is plan 016's subject, not this plan's.
- `backend/agentaudit/worker.py` — it already builds the correct redactor and
  already passes it to `runner.run`. Nothing to change.
- Anything near `runner.py:485` (`IsolatedRunner(...)` construction). Plan 015
  edits that region of the same file; stay out of it to avoid a merge conflict.

## Git workflow

- Branch off `develop`: `git checkout -b fix/014-redactor-reaches-attacker-and-judge develop`
- Conventional-commit subject, e.g.
  `fix: redact with the run's redactor before calling the attacker model`
- Commit message must end with:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Let `build_refining_strategy` accept and forward a redactor

In `backend/agentaudit/core/attacker.py`, add a `redactor: Redactor | None = None`
parameter to `build_refining_strategy` and forward it to `RefiningStrategy`.

Place the new parameter **after** `judge` (i.e. last) so no existing positional
call changes meaning. Forward it as `redactor=redactor`.

Confirm `Redactor` is already imported in this module — it is used at
`attacker.py:234` — so no new import should be needed. If ruff reports an
unused or misordered import, fix it in place.

**Verify**: `python -m pytest tests/test_attacker.py` → all pass (no behavior
change yet; this step must not break anything).

### Step 2: Let `build_judge` accept and forward a redactor

Same change in `backend/agentaudit/core/judge.py`: add
`redactor: Redactor | None = None` to `build_judge` (placed last), and forward
it as `redactor=redactor` to `ModelJudge`.

**Verify**: `python -m pytest tests/test_judge.py` → all pass.

### Step 3: Pass the run's redactor from the runner

In `backend/agentaudit/core/runner.py`, `_run_turns` must hand its `redactor` to
both builders:

```python
        judge = build_judge(log=judge_log, redactor=redactor)
        strategy = build_refining_strategy(
            test.input, test.adaptive, log=refinement_log, judge=judge, redactor=redactor
        ) or build_strategy(test.input, test.adaptive, judge)
```

**Before writing this, confirm `_run_turns` actually has `redactor` in scope.**
Read the enclosing function definition. If the redactor is held by `run_one` but
not passed down into `_run_turns`, you must thread it through as a parameter —
add `redactor: Redactor` to `_run_turns`'s signature and pass it from the single
call site in `run_one`. Do not reach for a module-level or global redactor.

Also extend the existing comment above the builders to say why the redactor is
passed — one sentence, matching the house register, e.g. that the run's redactor
carries resolved credential literals the built-in patterns do not know about.

**Verify**: `python -m pytest tests/test_runner.py` → all pass.

### Step 4: Add the regression tests

See "Test plan" below for the exact cases.

**Verify**: `python -m pytest tests/test_attacker.py tests/test_judge.py` → all
pass, including the new tests.

### Step 5: Full validation

**Verify**:

- `python -m ruff check .` → `All checks passed!`
- `python -m pytest` → `1066 passed` or more, `0 failed`

## Test plan

The point of these tests is that a literal known only to the run's redactor —
not matched by any built-in pattern — never appears in the text sent to the
model. Pick a literal that the built-in patterns provably do **not** match, so
the test fails today for the right reason. A plain nonsense token such as
`"hunter2-not-a-pattern"` works; do **not** use something shaped like `sk-...`
or `Bearer ...`, because the built-in patterns already catch those and the test
would pass even without the fix.

**New in `tests/test_attacker.py`:**

1. `build_refining_strategy(..., redactor=Redactor(RedactionConfig(literals=[SECRET])))`
   with a stub `AttackerModel` that records the `user` prompt it is given. Drive
   one turn with a history entry whose `text` contains `SECRET`. Assert `SECRET`
   does not appear in the recorded prompt, and that the mask token does.
2. The negative control: build with no `redactor` and assert `SECRET` **does**
   appear — this pins the fact that the built-in patterns do not cover it, so
   test 1 is measuring the fix and not a coincidence.

**New in `tests/test_judge.py`:**

3. `build_judge(redactor=Redactor(RedactionConfig(literals=[SECRET])))` with a
   stub model recording its prompt; call `succeeded(goal, AgentResponse(text=...SECRET...))`
   and assert `SECRET` is absent from the recorded prompt.

**Structural pattern**: read the existing stub-model tests in
`tests/test_attacker.py` and `tests/test_judge.py` first and reuse whatever
stub/fake `AttackerModel` those files already define. Do not invent a second
stub if one exists. Both builders return `None` when no model is configured, so
you must pass a `model=` (attacker) or otherwise inject the stub the way the
existing tests do — follow their lead rather than setting environment variables.

**Verification**: `python -m pytest tests/test_attacker.py tests/test_judge.py`
→ all pass, including 3 new tests.

## Done criteria

ALL must hold:

- [ ] `python -m ruff check .` exits 0 with `All checks passed!`
- [ ] `python -m pytest` exits 0 with at least `1066 passed`, `0 failed`
- [ ] `grep -n "build_judge(log=judge_log)" backend/agentaudit/core/runner.py`
      returns no matches (the un-redacted call site is gone)
- [ ] `grep -n "redactor" backend/agentaudit/core/judge.py` shows `redactor` in
      `build_judge`'s signature, not only in `ModelJudge.__init__`
- [ ] 3 new tests exist across `tests/test_attacker.py` and `tests/test_judge.py`
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/README.md` status row for 014 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts in "Current state" do not match the live code — the codebase has
  drifted since this plan was written.
- `RefiningStrategy.__init__` or `ModelJudge.__init__` no longer accepts a
  `redactor` argument. This plan assumes the constructors are already correct
  and only the builders are missing the parameter.
- The negative-control test (case 2) fails — i.e. the secret is masked even
  without passing a redactor. That would mean a built-in pattern already covers
  your chosen literal; pick a different literal and retry once. If it still
  happens, stop: the premise needs rechecking.
- Threading `redactor` into `_run_turns` appears to require changing
  `run_one`'s public signature or any file outside the in-scope list.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- The invariant to preserve: **every** object that sends run evidence to a
  third party must be constructed with the run's redactor, not a default one.
  There are currently two such objects (`RefiningStrategy`, `ModelJudge`). If a
  third is added, it owes the same wiring, and its builder must expose the
  parameter — the constructors' safe defaults are a backstop, not the design.
- A reviewer should check that the redactor reaching these builders is the one
  built in `worker.py:203-208` (with resolved secrets folded into `literals`),
  not a freshly constructed `Redactor(target.evidence.redact)`. Only the former
  knows the resolved credential values.
- Plan 015 changes a different region of `runner.py` (the `IsolatedRunner`
  construction around line 485). Land this plan first; 015 is written to expect
  it.
- Deferred out of this plan: `RefinementLog`/`JudgeLog` contents are not
  redacted here. They record model-written attack turns and rationales, which
  are model output rather than agent evidence, but if those logs are ever
  persisted or exported, they need their own pass.
