"""Compare two runs so agentaudit works as a release-safety system."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from agentaudit.core.findings import FAILING
from agentaudit.core.schema import Risk, RunResult, Status, TestResult
from agentaudit.core.scoring import ScoreReport

# An error rate at or above this is worth surfacing on its own: at half the
# suite unable to reach a verdict, the score is computed on a minority of the
# tests and is not a number anyone should act on.
ERROR_RATE_FLOOR = 0.5

# ...and it must also be a jump, not this target's normal. Compared against the
# trailing median rather than the mean: a target with one previous bad run
# would drag a mean up far enough to hide the next one.
ERROR_RATE_JUMP = 0.3

# Below this many prior runs there is no baseline to call anything a jump
# against, so a first bad run is reported as `no_baseline` instead -- which is
# the real shape of the corpus: five of the six 4 Sep spikes are an agent's
# first ever run, where the rate never "spiked" because nothing preceded it.
MIN_BASELINE_RUNS = 3


@dataclass
class _Buckets:
    newly_failing: list[str] = field(default_factory=list)
    newly_passing: list[str] = field(default_factory=list)
    still_failing: list[str] = field(default_factory=list)
    critical_regressions: list[str] = field(default_factory=list)


class TestDelta(BaseModel):
    test_id: str
    before: Status | None
    after: Status | None
    latency_before_ms: float | None
    latency_after_ms: float | None


class RunDiff(BaseModel):
    newly_failing: list[str] = Field(default_factory=list)
    newly_passing: list[str] = Field(default_factory=list)
    still_failing: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    latency_deltas: list[TestDelta] = Field(default_factory=list)
    score_delta: dict[str, float] = Field(default_factory=dict)
    critical_regressions: list[str] = Field(default_factory=list)


def _classify(
    test_id: str,
    after_result: TestResult,
    before_status: Status | None,
    buckets: _Buckets,
) -> None:
    after_status = after_result.status
    was_ok = before_status is None or before_status == Status.passed
    is_bad = after_status in FAILING
    was_bad = before_status in FAILING
    is_ok = after_status == Status.passed

    if was_ok and is_bad:
        buckets.newly_failing.append(test_id)
        if after_result.risk == Risk.critical:
            buckets.critical_regressions.append(test_id)
    elif was_bad and is_ok:
        buckets.newly_passing.append(test_id)
    elif was_bad and is_bad:
        buckets.still_failing.append(test_id)


def compare(
    before: RunResult,
    after: RunResult,
    before_score: ScoreReport,
    after_score: ScoreReport,
) -> RunDiff:
    before_by_id = {r.test_id: r for r in before.results}
    after_by_id = {r.test_id: r for r in after.results}

    added = sorted(after_by_id.keys() - before_by_id.keys())
    removed = sorted(before_by_id.keys() - after_by_id.keys())

    buckets = _Buckets()

    for test_id, after_result in after_by_id.items():
        before_result = before_by_id.get(test_id)
        before_status = before_result.status if before_result else None
        _classify(test_id, after_result, before_status, buckets)

    latency_deltas = [
        TestDelta(
            test_id=test_id,
            before=before_by_id[test_id].status,
            after=after_by_id[test_id].status,
            latency_before_ms=before_by_id[test_id].latency_ms,
            latency_after_ms=after_by_id[test_id].latency_ms,
        )
        for test_id in before_by_id.keys() & after_by_id.keys()
    ]
    latency_deltas.sort(
        key=lambda d: (d.latency_after_ms or 0) - (d.latency_before_ms or 0),
        reverse=True,
    )

    before_cat = {c.category.value: c.score for c in before_score.category_scores}
    after_cat = {c.category.value: c.score for c in after_score.category_scores}

    score_delta = {
        "overall": after_score.overall_score - before_score.overall_score,
        "pass_rate": after_score.pass_rate - before_score.pass_rate,
    }
    for category in before_cat.keys() | after_cat.keys():
        score_delta[category] = after_cat.get(category, 0.0) - before_cat.get(
            category, 0.0
        )

    return RunDiff(
        newly_failing=sorted(buckets.newly_failing),
        newly_passing=sorted(buckets.newly_passing),
        still_failing=sorted(buckets.still_failing),
        added=added,
        removed=removed,
        latency_deltas=latency_deltas,
        score_delta=score_delta,
        critical_regressions=sorted(buckets.critical_regressions),
    )


class ErrorRateIncident(BaseModel):
    """A run whose error rate is too high for its score to be trusted.

    Not a finding about the agent: an errored test reached no verdict, so this
    says the *run* is unreliable, which is why it is surfaced above the score
    rather than inside it.
    """

    error_rate: float
    baseline: float | None
    errored: int
    total: int
    # True when there was not enough history to compare against, so the run is
    # flagged on its absolute rate alone.
    no_baseline: bool


def error_rate(results: list[TestResult]) -> float:
    """Share of results that errored. 0.0 for an empty run."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.status == Status.error) / len(results)


def detect_error_rate_incident(
    run: RunResult, prior_rates: list[float]
) -> ErrorRateIncident | None:
    """Flag a run whose error rate makes its score meaningless.

    `prior_rates` is this target's earlier error rates, oldest first; the
    caller supplies them (the store owns that query, this module owns the
    rule). Returns None when the run is normal for the target.

    Two ways to trip, because the corpus contains both shapes:

    - **A jump.** The rate is at least `ERROR_RATE_FLOOR` and exceeds the
      trailing median by `ERROR_RATE_JUMP`. This is the `bare-echo` case:
      two clean runs, then every test errors.
    - **No baseline.** The rate is at least `ERROR_RATE_FLOOR` and there is
      not enough history to compare. This is what the 4 Sep railway cluster
      actually is -- each agent's first run erroring outright, then recovering
      to 0.15-0.25 once configured. A pure jump rule would miss all five,
      which is exactly the silent-bad-run case this exists to catch.
    """
    rate = error_rate(run.results)
    if rate < ERROR_RATE_FLOOR:
        return None

    errored = sum(1 for r in run.results if r.status == Status.error)
    if len(prior_rates) < MIN_BASELINE_RUNS:
        return ErrorRateIncident(
            error_rate=rate,
            baseline=None,
            errored=errored,
            total=len(run.results),
            no_baseline=True,
        )

    baseline = statistics.median(prior_rates)
    if rate - baseline < ERROR_RATE_JUMP:
        return None
    return ErrorRateIncident(
        error_rate=rate,
        baseline=baseline,
        errored=errored,
        total=len(run.results),
        no_baseline=False,
    )
