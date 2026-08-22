# feat/evolve — Spec

**Files:** `agentaudit/core/evolve.py`, `agentaudit/core/archive.py`,
`agentaudit/cli.py` (`evolve_cmd`), `tests/test_evolve.py`, `tests/test_archive.py`

## Goal

The packs are a fixed corpus: everything a run discovers dies with the run. This closes
the loop — pick an uncovered cell, ask a model for an attack aimed at it, validate it,
run it, keep it if it is novel. What survives is an ordinary `TestCase` that runs
offline forever after, with no model involved.

## Public API

```python
class AttackGenerator(Protocol):
    def complete(self, system: str, user: str) -> str: ...

@dataclass(frozen=True)
class EvolveBudget:
    max_candidates: int = 20
    max_kept: int = 10
    wall_clock_s: float = 600.0

@dataclass
class EvolveResult:
    kept: list[Candidate]
    archive: Archive | None
    rejected: list[tuple[str, str]]     # (test_id, reason) — including invalid replies
    candidates_generated: int
    runs_spent: int
    stopped_because: str
    def as_pack_rows() -> list[dict]    # ready for store.save_pack_test

def evolve(generator, run_fn, *, archive=None, categories=None, budget=None, now=...) -> EvolveResult
def next_cell(archive, categories) -> tuple[Category, str] | None
def build_generator() -> AttackGenerator | None
def expired(run_count, keep_runs=5, *, still_failing=False) -> bool
```

## Configuration

Reuses the attacker model's variables — `AGENTAUDIT_ATTACKER_ENDPOINT` +
`AGENTAUDIT_ATTACKER_MODEL`, optional `AGENTAUDIT_ATTACKER_API_KEY`. A second set for the
same OpenAI-compatible POST would be configuration for its own sake.

Any OpenAI-compatible endpoint works. A fully local campaign needs no key and sends
nothing off the machine:

```bash
export AGENTAUDIT_ATTACKER_ENDPOINT=http://localhost:11434/v1/chat/completions
export AGENTAUDIT_ATTACKER_MODEL=llama3.1
export AGENTAUDIT_EGRESS_ALLOW_LOCAL=1
```

Credentials come from the process environment, never from target config — same reasoning
as `attacker.py`: a target file is partner-supplied, and one that could name its own
credential variable would be an exfiltration primitive.

## Design decisions

- **The loop lives above `runner.run`, not inside it.** `run` takes a fixed list, never
  raises, and executes each test in a spawned child; a strategy inside it sees one test's
  history and cannot write anywhere. `evolve` takes `run_fn` — in practice
  `audit.execute` — so generated tests get the same isolation, redaction and egress
  validation as hand-written ones. Evolution gets no privileged route to the agent.
- **The existing validator is the safety gate.** Every candidate goes through
  `load_tests_from_rows`, which rejects unknown assertions, unknown strategies, bad enums
  and malformed ids. A model can only compose the nineteen assertions that exist; it
  cannot invent a predicate. Anything that fails is discarded, never repaired — repairing
  a malformed test means guessing what it meant to assert.
- **Novelty is checked before the target is queried.** A near-duplicate costs ~2.5s of
  process spawn to learn nothing. Rejecting it first is most of what makes a campaign
  affordable (the TAP / AutoRedTeamer result). `tests/test_evolve.py` asserts `run_fn`
  was never called on that path — the cost property is a tested invariant, not a hope.
- **The cell's style is applied here, not asked for.** A model told "write this in base64"
  produces unreliable base64; `TRANSFORMS[style]` does it exactly. This is also what makes
  the candidate land in the cell it was aimed at — without it every candidate would be
  `plain` and the targeted cell would never fill, so the loop would re-probe one cell
  forever.
- **Ids are content-derived.** `generated.<namespace>.<sha256(probe)[:10]>`, plus
  `__<transform>` for a styled variant. `test-packs.md` calls the id the stable identifier
  regression comparison keys on, so a counter or a timestamp would break
  `agentaudit compare` history for every generated test. The namespace is restricted to
  `compliance.OWASP_BY_PACK` keys because `_pack_of` maps ASI controls off the second
  dotted segment; an id outside that set maps to no control and quietly weakens the
  compliance report.
- **An unlanded attack is still kept.** A cell holding a tried-and-failed attack is
  honestly different from an empty one, and discarding it would overstate how much ground
  is untested.
- **`Status.error` is not a landing.** A harness failure is not evidence about the agent.
- **Budgets are mandatory.** An unbounded loop against a metered endpoint is the failure
  mode that makes the feature unshippable; "the model will stop on its own" is not a
  budget. Three independent ceilings, and the stop reason is reported.
- **A generator failure ends the campaign without raising.** A model that answers badly
  costs one candidate and the loop continues; a model that is unreachable stops it. Both
  are recorded in `rejected` / `stopped_because`.

## Retention

Provisional tests expire after `--keep-runs` runs (default 5); promoted ones never do.
Expiry is a **derived count** from existing `test_results` rows, not a new column or a
background job, and it means *stop selecting*, never *delete* — the pack row and every
historical result stay, because deleting evidence would break `agentaudit compare` and
collide with the ten-year retention the EU GPAI Code of Practice expects.

A test that is still catching a defect never expires. Retiring a live finding to save
runtime is the one outcome this must not produce — the same fail-closed instinct as
`scoring.py`'s empty-run path.

## The archive

`core/archive.py` is a MAP-Elites grid (Rainbow Teaming, arXiv 2402.16822): `Category` ×
attack style, one elite per cell. A candidate competes only against the incumbent *of its
own cell*, so diversity is a property of the data structure rather than something the
search is rewarded for. Without it, scalar attack-success optimisation converges: hundreds
of near-copies of one jailbreak and no probe in eight other categories.

Novelty is `difflib.SequenceMatcher`, not BLEU and not embeddings. It catches the trivial
parameter swap (0.96 on `pay INV-1` / `pay INV-2`) and does **not** catch paraphrase (0.56
on `ignore previous instructions` / `disregard prior directives`). The `# ponytail:`
comment names that ceiling rather than implying the check is stronger than it is.

`build()` sorts by test id before folding, so admission order cannot change the result.
That is correctness, not tidiness: `regressions.py` diffs by `test_id`, and an archive
that shifted between identical runs would report phantom coverage changes.

## Testing

`tests/test_evolve.py` — 22 tests, entirely offline against a stub generator; no test
makes a network call. The load-bearing ones: off-by-default (and not half-enabled by a
partial configuration), invalid replies discarded rather than raised, the pre-execution
duplicate rejection asserting `run_fn` was never called, all three budgets, and id
stability across identical campaigns.

`tests/test_archive.py` — 19 tests, including order-independence.

Verified end to end against a stub OpenAI-compatible endpoint: three candidates generated
into three *different* cells, persisted, then re-run with every `AGENTAUDIT_ATTACKER_*`
variable unset — they pass offline, deterministically, with no network.
