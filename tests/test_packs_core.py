from agentkit.core.config import CallableSpec, TargetConfig
from agentkit.core.loader import discover
from agentkit.core.runner import run
from agentkit.core.schema import Status

PACK_DIR = "agentkit/packs/core"


def test_discover_core_pack_no_loader_error():
    tests = discover(PACK_DIR)
    assert len(tests) >= 10
    ids = [t.id for t in tests]
    assert len(ids) == len(set(ids))


def test_core_pack_runs_against_safe_agent_no_crashes_and_injection_leakage_pass():
    tests = discover(PACK_DIR)
    cfg = TargetConfig(
        id="core-pack-demo",
        agent=CallableSpec(
            type="callable",
            callable="agentkit.packs.core._demo_safe_agent:create_agent",
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
