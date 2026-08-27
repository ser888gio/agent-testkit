"""Branching campaigns: iterative, Crescendo/TAP-style escalation, composed.

CLAUDE.md milestone 4 ("iterative attack loop with branching and retries") is
the one product-loop stage this repo has not shipped. Every primitive it needs
already exists -- this module does not add a new attack engine, it wires four
together:

- `archive.py:Archive` gives coverage-keyed goal selection instead of
  hammering one framing.
- `evolve.py:evolve` is already generate -> validate -> run -> admit, and
  already builds an `adaptive` `TestCase` when the archive hands it a
  strategy-style cell (`crescendo`, `sequential`, `linear`,
  `bad_likert_judge`). That is the branching loop: each ladder rung is one
  turn generated in reaction to the agent's last reply.
- `attacker.py:build_refining_strategy` is what makes a rung *react* instead
  of following a fixed script -- `evolve()` grew a `refine` flag for exactly
  this (see below).
- `judge.py:build_judge` is the stop condition every ladder already consults.
  A campaign does not touch it or duplicate it.

A campaign is therefore `evolve()` restricted to strategy-style cells, with
`refine=True` so admitted turns are attacker-model-written where a model is
configured. `evolve()` was extended with two keyword-only parameters
(`styles`, `refine`) rather than forked, so this file is a thin policy layer:
which cells count as "branching", and what counts as a sane default budget.
Survivors are admitted through the exact same `Archive`/`EvolveResult` queue
`evolve` already uses -- there is no second review path.

Offline-degradable by construction: `refine=True` only takes effect once
`build_refining_strategy` finds an attacker model, same gate as
`refined_pressure.yaml`. With no `AGENTAUDIT_ATTACKER_ENDPOINT`/`_MODEL`
configured, a campaign's generated ladder tests still need `build_generator()`
to produce *candidates* -- so a campaign is off entirely, same as `evolve`,
until an attacker model exists. That is deliberate: there is nothing for a
campaign to branch with if there is no model to write a goal or a turn.

Scoped out (see PRD-010): TAP's tree-of-variants-with-pruning. This ships
Crescendo/sequential/linear/bad_likert_judge branching (turn-level, reacting
to one transcript) with MAP-Elites cell selection standing in for TAP's
breadth search across framings. A true TAP tree -- multiple sibling
continuations per turn, scored and pruned before the best is sent -- is a
follow-up; `evolve`'s pre-execution novelty check already prunes duplicate
*goals* before a run is spent, which is the same instinct at the goal level.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from agentaudit.core.adaptive import STRATEGIES
from agentaudit.core.archive import Archive, Candidate
from agentaudit.core.evolve import AttackGenerator, EvolveBudget, EvolveResult
from agentaudit.core.evolve import evolve as run_evolution
from agentaudit.core.schema import Category, RunResult, TestCase

# The branching styles a campaign is allowed to pick from -- every ladder in
# adaptive.py, and nothing else. `evolve()`'s `plain`/transform cells are
# single-turn and already served by plain `evolve`; this module exists only
# for the styles that generate a turn per rung.
BRANCHING_STYLES: frozenset[str] = frozenset(STRATEGIES)

# Escalation depth per campaign member. Higher than `AdaptiveSpec`'s own
# default (4) because a campaign is specifically here to push further than
# the fixed ladders do; still well under the schema's ge=1, le=20 ceiling.
DEFAULT_MAX_TURNS = 8


@dataclass(frozen=True)
class CampaignBudget:
    """Ceilings on one campaign, in the same spirit as `EvolveBudget`.

    Turns are bounded per candidate (`max_turns`, mirrored onto each
    generated test's `AdaptiveSpec`) and candidates/wall-clock are bounded
    campaign-wide via the wrapped `EvolveBudget` -- so the total turn budget
    for a campaign is `max_candidates * max_turns` in the worst case, still a
    hard ceiling, never "the model will stop on its own".
    """

    max_candidates: int = 10
    max_kept: int = 5
    wall_clock_s: float = 600.0
    max_turns: int = DEFAULT_MAX_TURNS

    def as_evolve_budget(self) -> EvolveBudget:
        return EvolveBudget(
            max_candidates=self.max_candidates,
            max_kept=self.max_kept,
            wall_clock_s=self.wall_clock_s,
        )


@dataclass
class CampaignResult:
    """What one campaign found. A thin view over `EvolveResult`.

    Kept as its own type (rather than returning `EvolveResult` directly) so a
    caller reading `campaign.py` never has to know the branching loop is
    implemented on top of `evolve()` -- that is this module's decision to
    revisit, not its callers'.
    """

    kept: list[Candidate] = field(default_factory=list)
    archive: Archive | None = None
    rejected: list[tuple[str, str]] = field(default_factory=list)
    candidates_generated: int = 0
    runs_spent: int = 0
    stopped_because: str = ""

    def as_pack_rows(self) -> list[dict]:
        """The kept tests, ready for `store.save_pack_test` -- same review
        queue `agentaudit evolve` already feeds."""
        return [c.test.model_dump(mode="json", exclude_defaults=True) for c in self.kept]

    @classmethod
    def _from_evolve(cls, result: EvolveResult) -> CampaignResult:
        return cls(
            kept=result.kept,
            archive=result.archive,
            rejected=result.rejected,
            candidates_generated=result.candidates_generated,
            runs_spent=result.runs_spent,
            stopped_because=result.stopped_because,
        )


def run_campaign(
    generator: AttackGenerator,
    run_fn: Callable[[list[TestCase]], RunResult],
    *,
    archive: Archive | None = None,
    categories: Sequence[Category] | None = None,
    budget: CampaignBudget | None = None,
) -> CampaignResult:
    """One branching campaign: goal seeding -> escalating turns -> admit.

    `run_fn` is the ordinary audit path (`audit.execute`), exactly as
    `evolve()` expects -- a campaign gets no privileged route to the agent,
    and every turn it sends goes through the same isolation, redaction and
    egress validation as a hand-written test. `archive` lets a caller seed
    coverage from a prior run (e.g. a fixed-ladder pack already executed) so
    the campaign spends its budget on cells that pack left uncovered, rather
    than re-discovering them.
    """
    budget = budget or CampaignBudget()
    result = run_evolution(
        generator,
        _bound_turns(run_fn, budget.max_turns),
        archive=archive,
        categories=categories,
        budget=budget.as_evolve_budget(),
        styles=BRANCHING_STYLES,
        refine=True,
    )
    return CampaignResult._from_evolve(result)


def _bound_turns(
    run_fn: Callable[[list[TestCase]], RunResult], max_turns: int
) -> Callable[[list[TestCase]], RunResult]:
    """Clamp each generated test's `AdaptiveSpec.max_turns` to the campaign budget.

    `evolve._build_test` sets `adaptive.strategy`/`refine` but has no notion of
    a campaign-level turn ceiling, and there is no clean seam to pass one
    through without widening `evolve()`'s contract further than this feature
    needs. Clamping the tests right before they reach `run_fn` keeps that
    ceiling enforced without evolve.py knowing campaigns exist.
    """

    def _wrapped(tests: list[TestCase]) -> RunResult:
        clamped = [
            t.model_copy(
                update={"adaptive": t.adaptive.model_copy(update={"max_turns": max_turns})}
            )
            if t.adaptive is not None and t.adaptive.max_turns > max_turns
            else t
            for t in tests
        ]
        return run_fn(clamped)

    return _wrapped
