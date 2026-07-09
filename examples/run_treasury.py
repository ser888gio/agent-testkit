"""Programmatic demo: load target, discover, run, score, print.

Run with: python examples/run_treasury.py
"""

from __future__ import annotations

import agentkit.domains.treasury.sandbox  # noqa: F401 - registers "treasury"
from agentkit.core.config import load_target
from agentkit.core.loader import discover
from agentkit.core.runner import run
from agentkit.core.scoring import score


def main() -> None:
    cfg = load_target("agentkit/config/treasury-agent.yaml")
    tests = discover("agentkit/packs/treasury")
    rr = run(cfg, tests)
    report = score(rr)

    print(f"Ran {len(rr.results)} tests against {rr.agent_name}")
    for r in rr.results:
        print(f"  [{r.status.value:>7}] {r.test_id}")

    print(
        f"Overall (weighted): {report.overall_score:.0%}  "
        f"Pass rate: {report.pass_rate:.0%}  "
        f"Critical failures: {report.critical_failures}"
    )
    print(f"Gate: {'PASS' if report.gate_passed else 'BLOCK'}")


if __name__ == "__main__":
    main()
