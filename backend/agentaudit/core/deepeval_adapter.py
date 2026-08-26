"""Normalization for DeepEval ``--json-output`` reports into agentaudit results.

This is scaffolding for the DeepEval external adapter (PRD-002): the category
table and the pure report normalizer live here so the offline half can be
reviewed and tested on its own. Subprocess execution and wiring into the
`ExternalEvalAdapter` lifecycle (catalog/execute, as promptfoo and garak do)
arrive in a follow-up change.

DeepEval is not a dependency; everything here works from a recorded JSON
artifact the operator produced. Metric names are canonicalized before lookup
("Faithfulness Metric" and "faithfulness" resolve identically), and any metric
the table does not know lands on the fallback category rather than raising --
a renamed metric must not crash a run that already happened. Error and reason
text from the report passes through the `Redactor`, because evidence from an
external tool never passes through `runner.py`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from agentaudit.core.adapters import _risk_for, _safe_id
from agentaudit.core.redaction import EvidencePolicy, Redactor
from agentaudit.core.schema import AssertionResult, Category, Risk, Status, TestResult

# Where an unrecognized metric lands. Reliability is the honest default: it
# says "quality signal we could not classify", not a claim of precision.
DEEPEVAL_FALLBACK_CATEGORY = Category.reliability

# DeepEval metric name -> agentaudit category. Keys are canonical forms (lower,
# non-alphanumerics folded to "_", trailing "metric" stripped); see
# `_canonical_metric`. Kept explicit rather than pattern-matched so a new or
# renamed metric degrades to the fallback visibly instead of silently.
DEEPEVAL_CATEGORY_MAP: dict[str, Category] = {
    # Factual grounding and answer quality.
    "answer_relevancy": Category.instruction_following,
    "correctness": Category.reliability,
    "faithfulness": Category.reliability,
    "hallucination": Category.reliability,
    "summarization": Category.reliability,
    "g_eval": Category.reliability,
    "topic_adherence": Category.instruction_following,
    "task_completion": Category.instruction_following,
    "prompt_alignment": Category.instruction_following,
    "goal_accuracy": Category.instruction_following,
    # Retrieval context quality -- how well memory/context served the answer.
    "contextual_precision": Category.memory_context,
    "contextual_recall": Category.memory_context,
    "contextual_relevancy": Category.memory_context,
    # Conversational state carried across turns.
    "conversation_completeness": Category.memory_context,
    "conversation_relevancy": Category.memory_context,
    "knowledge_retention": Category.memory_context,
    # Safety of what the model produces.
    "toxicity": Category.instruction_following,
    "bias": Category.instruction_following,
    "sexist": Category.instruction_following,
    "racist": Category.instruction_following,
    "red_teaming": Category.prompt_injection,
    "safety": Category.action_safety,
    # Agentic behaviour.
    "tool_correctness": Category.tool_use,
    "plan_adherence": Category.tool_use,
}

_METRIC_NOISE_RE = re.compile(r"[^a-z0-9]+")


def _canonical_metric(name: Any) -> str:
    """Fold a report's metric label onto its table key.

    DeepEval writes human labels ("Answer Relevancy Metric") while the table is
    keyed on canonical ids ("answer_relevancy"), so both spellings resolve.
    """
    cleaned = _METRIC_NOISE_RE.sub("_", str(name).strip().lower()).strip("_")
    return cleaned.removesuffix("_metric")


def deepeval_category(metric: str) -> Category:
    """The agentaudit category for one DeepEval metric, fallback when unknown."""
    return DEEPEVAL_CATEGORY_MAP.get(_canonical_metric(metric), DEEPEVAL_FALLBACK_CATEGORY)


def _deepeval_rows(report: Any) -> list[dict[str, Any]]:
    """Test-case rows of a parsed report; anything else is no results at all."""
    if not isinstance(report, dict):
        return []
    for key in ("test_cases", "tests"):
        rows = report.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _case_latency(case: dict[str, Any]) -> float | None:
    value = case.get("latency_ms", case.get("latency"))
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def normalize_deepeval_report(
    report: dict[str, Any],
    *,
    evidence: EvidencePolicy | None = None,
    started_at: datetime | None = None,
) -> list[TestResult]:
    """Turn one parsed DeepEval ``--json-output`` artifact into redacted results.

    Never raises: a malformed shape, a missing key, or a row of the wrong type
    yields fewer (or error-status) results, never an exception -- the caller's
    run already happened and must be reported either way. Verdicts come from
    DeepEval's own success flags; nothing is re-judged here.
    """
    evidence = evidence or EvidencePolicy()
    started_at = started_at or datetime.now(timezone.utc)
    redactor = Redactor(evidence.redact)
    return [
        _result_from_case(index, case, evidence, redactor, started_at)
        for index, case in enumerate(_deepeval_rows(report))
    ]


def _result_from_case(
    index: int,
    case: dict[str, Any],
    evidence: EvidencePolicy,
    redactor: Redactor,
    started_at: datetime,
) -> TestResult:
    metrics = case.get("metrics") or case.get("metrics_data")
    assertion_results: list[AssertionResult] = []
    errors: list[str] = []
    categories: list[Category] = []

    if isinstance(metrics, list):
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            metric_name = str(metric.get("name") or "unknown")
            categories.append(deepeval_category(metric_name))
            error_text = metric.get("error")
            if error_text:
                errors.append(redactor.redact_text(str(error_text)))
            passed = bool(metric.get("success"))
            detail = redactor.redact_text(str(metric.get("reason") or ""))
            assertion_results.append(
                AssertionResult(
                    name=f"deepeval:{_canonical_metric(metric_name)}",
                    passed=passed,
                    detail=detail,
                )
            )

    if not assertion_results:
        status = Status.error
        error = "deepeval test case carried no metric results"
    elif errors:
        status = Status.error
        error = "; ".join(errors)
    elif case.get("success") is False or not all(a.passed for a in assertion_results):
        # The case-level flag outranks the per-metric ones: trust the runner's
        # own verdict over our re-aggregation of it.
        status = Status.failed
        error = None
    else:
        status = Status.passed
        error = None

    request = redactor.redact(case.get("input")) if evidence.store_request else None
    response = redactor.redact(case.get("actual_output")) if evidence.store_response else None

    category = _category_for(categories)
    return TestResult(
        test_id=_safe_id("deepeval", case.get("name") or index),
        category=category,
        risk=_risk_for(category),
        status=status,
        latency_ms=_case_latency(case),
        assertion_results=assertion_results,
        request=request,
        response=response,
        error=error,
        started_at=started_at,
        finished_at=started_at,
    )


def _category_for(categories: list[Category]) -> Category:
    """One category per test case: the highest-risk metric wins.

    A case can carry several metrics with different categories, but a result
    holds one; risk is what the CI gate reads, so the strictest applies.
    """
    for category in categories:
        if _risk_for(category) is Risk.high:
            return category
    return categories[0] if categories else DEEPEVAL_FALLBACK_CATEGORY
