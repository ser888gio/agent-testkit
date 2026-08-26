import pytest

from agentaudit.core.compliance import CONTROLS_BY_CATEGORY
from agentaudit.core.deepeval_adapter import (
    DEEPEVAL_CATEGORY_MAP,
    DEEPEVAL_FALLBACK_CATEGORY,
    deepeval_category,
    normalize_deepeval_report,
)
from agentaudit.core.redaction import EvidencePolicy
from agentaudit.core.schema import Category, Risk, Status

# Shaped like `deepeval test run --json-output`: one entry per test case, each
# carrying its own success flag and per-metric verdicts.
DEEPEVAL_REPORT = {
    "test_cases": [
        {
            "name": "test_refund_window",
            "success": True,
            "latency": 412.5,
            "input": "What is our refund window? sk-abcdefgh12345678",
            "actual_output": "30 days, no questions asked.",
            "metrics": [
                {
                    "name": "answer relevancy",
                    "score": 0.9,
                    "threshold": 0.7,
                    "success": True,
                },
                {"name": "Faithfulness Metric", "score": 1.0, "success": True},
            ],
        },
        {
            "name": "test_angry_customer",
            "success": False,
            "latency_ms": 380,
            "input": "You people are useless",
            "actual_output": "Then take your business elsewhere.",
            "metrics": [
                {"name": "toxicity", "score": 0.8, "threshold": 0.5, "success": False},
                {"name": "bias", "score": 0.1, "threshold": 0.5, "success": True},
            ],
        },
        {
            "name": "test_tool_call",
            "success": False,
            "metrics": [{"name": "tool_correctness", "score": 0.0, "success": False}],
        },
        {
            "name": "test_custom_metric",
            "success": False,
            "metrics": [
                {"name": "my_custom_groundedness", "score": 0.2, "success": False}
            ],
        },
    ]
}


def test_every_mapped_category_is_a_known_category():
    assert DEEPEVAL_CATEGORY_MAP, "the table must not be empty"
    for metric, category in DEEPEVAL_CATEGORY_MAP.items():
        assert isinstance(category, Category), f"{metric} maps to a non-category"
        # The registry every consumer derives controls from must know it too.
        assert category in CONTROLS_BY_CATEGORY, f"{metric} maps to an unmapped category"


def test_table_covers_the_documented_metric_families():
    documented = {
        "answer_relevancy",
        "faithfulness",
        "hallucination",
        "toxicity",
        "bias",
        "correctness",
        "tool_correctness",
    }
    assert documented <= set(DEEPEVAL_CATEGORY_MAP)


def test_metric_labels_canonicalize_onto_the_table():
    assert deepeval_category("Faithfulness Metric") is Category.reliability
    assert deepeval_category("Answer Relevancy Metric") is Category.instruction_following
    assert deepeval_category("TOXICITY") is Category.instruction_following


def test_unknown_metric_falls_back_instead_of_raising():
    assert deepeval_category("brand_new_v3_check") is DEEPEVAL_FALLBACK_CATEGORY


def test_results_normalize_with_statuses_categories_and_latency():
    results = normalize_deepeval_report(DEEPEVAL_REPORT)

    assert [r.status for r in results] == [
        Status.passed,
        Status.failed,
        Status.failed,
        Status.failed,
    ]
    passed, toxic, tool, custom = results
    assert passed.category is Category.instruction_following
    assert passed.latency_ms == 412.5
    assert toxic.category is Category.instruction_following
    assert toxic.latency_ms == 380.0
    # The highest-risk metric in the case decides the category.
    assert tool.category is Category.tool_use
    assert tool.risk is Risk.high
    # A metric the table does not know lands on the fallback, visibly failed.
    assert custom.category is DEEPEVAL_FALLBACK_CATEGORY
    assert all("." in r.test_id for r in results)


def test_evidence_is_redacted_and_policy_is_honoured():
    (passed, *_rest) = normalize_deepeval_report(DEEPEVAL_REPORT)
    assert "sk-abcdefgh12345678" not in str(passed.request)

    dropped = normalize_deepeval_report(
        DEEPEVAL_REPORT,
        evidence=EvidencePolicy(store_request=False, store_response=False),
    )
    assert all(r.request is None and r.response is None for r in dropped)


def test_metric_error_text_becomes_an_error_result_and_is_redacted():
    report = {
        "test_cases": [
            {
                "name": "test_broken_metric",
                "success": False,
                "metrics": [
                    {
                        "name": "faithfulness",
                        "error": "evaluation model call failed: Bearer sk-abcdefgh12345678",
                        "success": False,
                    }
                ],
            }
        ]
    }
    (result,) = normalize_deepeval_report(report)

    assert result.status is Status.error
    assert result.error is not None
    assert "sk-abcdefgh12345678" not in result.error


def test_a_case_with_no_metrics_is_an_error_not_a_pass():
    report = {"test_cases": [{"name": "test_empty", "success": True}]}
    (result,) = normalize_deepeval_report(report)
    assert result.status is Status.error
    assert "no metric results" in result.error


@pytest.mark.parametrize(
    "report",
    [
        None,
        {},
        [],
        "not a dict",
        {"test_cases": None},
        {"tests": []},
        {"test_cases": [None, "junk", 7]},
        {"unrelated": True},
    ],
)
def test_malformed_reports_never_raise(report):
    results = normalize_deepeval_report(report)
    assert isinstance(results, list)
    assert results == []


def test_rows_of_the_wrong_type_are_skipped_but_good_rows_survive():
    report = {
        "test_cases": [
            None,
            "junk",
            {
                "name": "test_ok",
                "success": True,
                "metrics": [{"name": "faithfulness", "success": True}],
            },
        ]
    }
    results = normalize_deepeval_report(report)
    assert [r.test_id for r in results] == ["deepeval.test_ok"]
