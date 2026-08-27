from agentaudit.core.config import CallableSpec, TargetConfig
from agentaudit.core.loader import discover
from agentaudit.core.runner import run
from agentaudit.core.schema import Status

PACK_DIR = "agentaudit/packs/core"

# PRD-012: three jailbreak-ladder tests used to carry a treasury `setup:` +
# `no_payment_created` in this domain-neutral pack, so they fabricated a
# FAILED result ("sandbox has no bank") against any agent run without a
# treasury sandbox -- including the safest possible one. Re-asserted here on
# response text, same as core.jailbreak.bad_likert_judge; the side-effect
# version of this coverage now lives in agentaudit/packs/treasury as
# treasury.jailbreak.*.
REASSERTED_JAILBREAK_TESTS = {
    "core.jailbreak.linear_concession",
    "core.jailbreak.refined_pressure",
    "core.jailbreak.sequential_decomposition",
}


def test_discover_core_pack_no_loader_error():
    tests = discover(PACK_DIR)
    assert len(tests) >= 10
    ids = [t.id for t in tests]
    assert len(ids) == len(set(ids))


def test_core_pack_declares_no_setup_and_is_sandbox_free():
    # Guardrail for PRD-012: packs/core is advertised as needing no sandbox, so
    # no test here may seed sandbox state that only a domain sandbox can
    # accept. A `setup:` key is exactly the signal a test depends on one.
    tests = discover(PACK_DIR)
    offenders = [t.id for t in tests if getattr(t, "setup", None)]
    assert not offenders, f"core pack tests must not declare setup: {offenders}"


def test_core_pack_runs_against_safe_agent_no_crashes_and_injection_leakage_pass():
    tests = discover(PACK_DIR)
    cfg = TargetConfig(
        id="core-pack-demo",
        agent=CallableSpec(
            type="callable",
            callable="agentaudit.packs.core._demo_safe_agent:create_agent",
        ),
    )
    rr = run(cfg, tests)

    assert len(rr.results) == len(tests)
    assert all(r.status != Status.error for r in rr.results)

    by_id = {r.test_id: r for r in rr.results}
    assert by_id["core.prompt_injection.instruction_override"].status == Status.passed
    assert (
        by_id["core.prompt_injection.system_prompt_extraction"].status == Status.passed
    )
    assert by_id["core.data_leakage.secret_probe"].status == Status.passed
    assert by_id["core.data_leakage.pii_probe"].status == Status.passed


def test_core_pack_runs_against_safe_agent_zero_failures_zero_skips():
    # PRD-012 success criterion: `agentaudit run core` against a sandbox-free
    # stub reports 0 failures and every test executed, none skipped.
    tests = discover(PACK_DIR)
    cfg = TargetConfig(
        id="core-pack-demo",
        agent=CallableSpec(
            type="callable",
            callable="agentaudit.packs.core._demo_safe_agent:create_agent",
        ),
    )
    rr = run(cfg, tests)
    assert len(rr.results) == len(tests) == 20
    statuses = {r.status for r in rr.results}
    assert statuses == {Status.passed}


def test_reasserted_jailbreak_tests_fail_against_a_naive_agent():
    # Pack quality bar: if the reckless demo agent passes a safety test, the
    # test asserts nothing. `_demo_naive_agent` is the sandbox-free foil to
    # `_demo_safe_agent`, over-compliant in its own words.
    tests = [t for t in discover(PACK_DIR) if t.id in REASSERTED_JAILBREAK_TESTS]
    assert len(tests) == len(REASSERTED_JAILBREAK_TESTS)

    cfg = TargetConfig(
        id="core-pack-naive",
        agent=CallableSpec(
            type="callable",
            callable="agentaudit.packs.core._demo_naive_agent:create_agent",
        ),
    )
    rr = run(cfg, tests)
    for r in rr.results:
        assert r.status == Status.failed, f"{r.test_id} did not catch it: {r.status}"
