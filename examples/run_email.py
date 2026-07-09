"""Programmatic demo: the exfiltration attack end-to-end against the email pack.

Run with: python examples/run_email.py
"""

from __future__ import annotations

import agentkit.domains.email.sandbox  # noqa: F401 - registers "email"
from agentkit.core.config import load_target
from agentkit.core.loader import discover
from agentkit.core.runner import run
from agentkit.core.scoring import score


def main() -> None:
    cfg = load_target("agentkit/config/email-agent.yaml")
    tests = discover("agentkit/packs/email")
    rr = run(cfg, tests)
    report = score(rr)

    print(f"Ran {len(rr.results)} tests against {rr.agent_name}")
    for r in rr.results:
        print(f"  [{r.status.value:>7}] {r.test_id}")

    exfil = next(r for r in rr.results if r.test_id == "email.exfiltration.blocked")
    verdict = (
        "clean - no mail reached the attacker"
        if exfil.status.value == "passed"
        else "LEAKED - the agent forwarded sensitive data externally"
    )
    print(f"\nExfiltration demo: {verdict}")
    print(
        f"Overall (weighted): {report.overall_score:.0%}  "
        f"Pass rate: {report.pass_rate:.0%}  "
        f"Critical failures: {report.critical_failures}"
    )
    print(f"Gate: {'PASS' if report.gate_passed else 'BLOCK'}")


if __name__ == "__main__":
    main()
