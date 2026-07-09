"""Compare two runs so agentkit works as a release-safety system."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentkit.core.schema import Risk, RunResult, Status
from agentkit.core.scoring import ScoreReport

_BAD = (Status.failed, Status.error)


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

    newly_failing: list[str] = []
    newly_passing: list[str] = []
    still_failing: list[str] = []
    critical_regressions: list[str] = []

    for test_id, after_result in after_by_id.items():
        before_result = before_by_id.get(test_id)
        before_status = before_result.status if before_result else None
        after_status = after_result.status

        was_ok = before_status is None or before_status == Status.passed
        is_bad = after_status in _BAD
        was_bad = before_status in _BAD
        is_ok = after_status == Status.passed

        if was_ok and is_bad:
            newly_failing.append(test_id)
            if after_result.risk == Risk.critical:
                critical_regressions.append(test_id)
        elif was_bad and is_ok:
            newly_passing.append(test_id)
        elif was_bad and is_bad:
            still_failing.append(test_id)

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
        key=lambda d: (d.latency_after_ms or 0) - (d.latency_before_ms or 0), reverse=True
    )

    before_cat = {c.category.value: c.score for c in before_score.category_scores}
    after_cat = {c.category.value: c.score for c in after_score.category_scores}

    score_delta = {
        "overall": after_score.overall_score - before_score.overall_score,
        "pass_rate": after_score.pass_rate - before_score.pass_rate,
    }
    for category in before_cat.keys() | after_cat.keys():
        score_delta[category] = after_cat.get(category, 0.0) - before_cat.get(category, 0.0)

    return RunDiff(
        newly_failing=sorted(newly_failing),
        newly_passing=sorted(newly_passing),
        still_failing=sorted(still_failing),
        added=added,
        removed=removed,
        latency_deltas=latency_deltas,
        score_delta=score_delta,
        critical_regressions=sorted(critical_regressions),
    )
