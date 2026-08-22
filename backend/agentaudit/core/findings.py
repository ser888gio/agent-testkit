"""What failed, in what order, and why.

Six modules used to answer these three questions for themselves: two identical
copies of the failure-first sort ordering, three near-copies of "the detail that
explains this failure", and eight spellings of the failure predicate itself --
close enough to look deliberate, different enough that fixing one fixed one.
`reports/compliance.py` reached into `reports/md.py`'s private helper rather than
write a fourth.

Control-plane only: it derives from an already-redacted `RunResult` and never
looks at a live agent. Renderers, the dashboard and the store consume this; none
of them derive.
"""

from __future__ import annotations

from collections.abc import Iterable

from agentaudit.core.schema import AssertionResult, Status, TestResult

# An error is a failure. A test that could not run is not evidence that the
# agent behaved, and reporting it as anything softer than a failure is how a
# broken endpoint scores green.
FAILING = (Status.failed, Status.error)

# Failures first, then everything else, skipped last. The reader is here for the
# failures; a report that buries them under fifty passes is a worse report.
_RANK = {Status.failed: 0, Status.error: 0, Status.passed: 1, Status.skipped: 2}


def is_failure(result: TestResult) -> bool:
    return result.status in FAILING


def failures(results: Iterable[TestResult]) -> list[TestResult]:
    """Only the failing results, ordered by test id."""
    return sorted((r for r in results if is_failure(r)), key=lambda r: r.test_id)


def order_by_failure(results: Iterable[TestResult]) -> list[TestResult]:
    """Every result, failures first, ties broken by test id."""
    return sorted(results, key=lambda r: (_RANK.get(r.status, 1), r.test_id))


def failed_assertions(result: TestResult) -> list[AssertionResult]:
    return [a for a in result.assertion_results if not a.passed]


def detail_for(result: TestResult) -> str:
    """The one line that explains a failure: first failing assertion, else the error."""
    failed = failed_assertions(result)
    if failed:
        return failed[0].detail
    return result.error or ""


def provenance_for(result: TestResult) -> str:
    """How this result's turns were produced, or "" for an ordinary scripted run.

    Kept beside `detail_for` so no renderer has to decide for itself what
    "model-written" means. A degraded run is called out explicitly: silence
    would let a report imply a model probed when it fell back to the script.
    """
    parts: list[str] = []
    if result.techniques:
        parts.append("via " + ", ".join(result.techniques))
    if result.degraded:
        parts.append("degraded to scripted ladder")
    return " ".join(parts)
