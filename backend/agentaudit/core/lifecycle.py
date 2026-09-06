"""Id and expiry rules for generated and promoted tests.

The rules a test's *identity* follows once it exists, separate from the loop
that creates one. `evolve.py` needs these, but so do four consumers that never
generate anything -- `reports/coverage.py`, `web/api.py`'s promotion queue,
`worker.py` and `incident_promotion.py`. Keeping them here means reading a
coverage report does not import an attacker-model client.

Pure derivation: no I/O, no model, no store.
"""

from __future__ import annotations

# Namespaces a generated test may claim. `compliance.py:_pack_of` keys the
# OWASP ASI mapping on the second dotted segment, so an id outside this set
# maps to no control and quietly weakens the compliance report. Restricting the
# generator's choice is cheaper than detecting the omission later.
GENERATED_PREFIX = "generated"
# Where a human-approved test lands. A distinct prefix is what lets a report
# count reviewed and unreviewed evidence separately.
PROMOTED_PREFIX = "promoted"


# Provisional tests expire; promoted ones do not. Five is enough for a
# candidate to prove itself across a few releases without the generated pack
# growing without bound -- at ~2.5s of process spawn per test, an unbounded
# pack quietly turns a two-minute suite into an hour.
DEFAULT_KEEP_RUNS = 5


def expired(
    run_count: int,
    keep_runs: int = DEFAULT_KEEP_RUNS,
    *,
    still_failing: bool = False,
) -> bool:
    """Whether a provisional test has outlived its trial.

    Expiry means "stop selecting it", never "delete it": the pack row and every
    historical result stay, because deleting evidence would break
    `agentaudit compare` and collide with the ten-year retention the EU GPAI
    Code of Practice expects.

    A test that is still catching a defect never expires. Retiring a live
    finding to save a few seconds of runtime is the one outcome this must not
    produce -- the same fail-closed instinct as `scoring.py`'s empty-run path.
    """
    if keep_runs <= 0:
        return False
    if still_failing:
        return False
    return run_count >= keep_runs


def promoted_id(test_id: str, namespace: str | None = None) -> str:
    """The id a generated test takes when a human promotes it.

    Promotion is the one moment a generated id changes, and it is deliberate:
    the `generated.` prefix is what marks a test as machine-authored and
    unreviewed, so a promoted test must not keep it. After this the id is
    frozen -- `regressions.py` keys history on it, and promotion therefore
    starts a fresh regression history for that test.

    The pack namespace is preserved so the OWASP ASI mapping survives; only the
    first segment moves.
    """
    parts = test_id.split(".")
    if parts[0] != GENERATED_PREFIX or len(parts) < 3:
        raise ValueError(f"not a generated test id: {test_id!r}")
    # Only the first segment moves: `generated.tool_misuse.abc` becomes
    # `promoted.tool_misuse.abc`, so `_pack_of` still reads `tool_misuse` and
    # the ASI mapping survives.
    return ".".join([namespace or PROMOTED_PREFIX, *parts[1:]])


def promotable(rows: list[dict], results_by_id: dict[str, str] | None = None) -> list[dict]:
    """Generated tests annotated with what a reviewer needs to decide.

    `still_failing` is surfaced rather than acted on: a test that is catching a
    defect is the most valuable thing in the queue and must not be quietly
    retired by expiry, but promoting it is still a human call.
    """
    statuses = results_by_id or {}
    out = []
    for row in rows:
        test_id = row.get("id", "")
        generated = test_id.startswith(f"{GENERATED_PREFIX}.")
        out.append(
            {
                **row,
                "promoted_id": promoted_id(test_id) if generated else test_id,
                "still_failing": statuses.get(test_id) in ("failed", "error"),
            }
        )
    return out
