from agentaudit.core.lifecycle import (
    DEFAULT_KEEP_RUNS,
    GENERATED_PREFIX,
    PROMOTED_PREFIX,
    expired,
    promotable,
    promoted_id,
)


def test_a_provisional_test_expires_after_its_trial_runs():
    assert expired(run_count=DEFAULT_KEEP_RUNS - 1) is False
    assert expired(run_count=DEFAULT_KEEP_RUNS) is True


def test_zero_keep_runs_disables_expiry():
    assert expired(run_count=1000, keep_runs=0) is False


def test_a_test_that_is_still_catching_a_defect_never_expires():
    # Retiring a live finding to save runtime is the one outcome this must
    # not produce.
    assert expired(run_count=99, keep_runs=5, still_failing=True) is False


def test_promotion_moves_only_the_first_segment():
    assert (
        promoted_id(f"{GENERATED_PREFIX}.tool_misuse.abc") == f"{PROMOTED_PREFIX}.tool_misuse.abc"
    )


def test_promotion_preserves_a_custom_namespace():
    assert (
        promoted_id(f"{GENERATED_PREFIX}.tool_misuse.abc", "reviewed") == "reviewed.tool_misuse.abc"
    )


def test_a_non_generated_id_cannot_be_promoted():
    for bad in ("core.tool_misuse.abc", f"{GENERATED_PREFIX}.abc", ""):
        try:
            promoted_id(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_promotable_annotates_generated_rows_and_passes_others_through():
    rows = [{"id": f"{GENERATED_PREFIX}.tool_misuse.abc"}, {"id": "core.tool_misuse.xyz"}]
    out = promotable(rows, {f"{GENERATED_PREFIX}.tool_misuse.abc": "failed"})
    assert out[0]["promoted_id"] == f"{PROMOTED_PREFIX}.tool_misuse.abc"
    assert out[0]["still_failing"] is True
    # A hand-written row keeps its own id and is never marked promotable.
    assert out[1]["promoted_id"] == "core.tool_misuse.xyz"
    assert out[1]["still_failing"] is False
