"""Shared non-test-collected fixtures for tests/test_cli.py."""

from __future__ import annotations

import re

# Every env var that can turn an LLM role on. Cleared together, because
# clearing a subset leaves the role configured by whatever is left.
LLM_ENV_VARS = (
    "AGENTAUDIT_LLM_CONFIG",
    "AGENTAUDIT_ATTACKER_ENDPOINT",
    "AGENTAUDIT_ATTACKER_MODEL",
    "AGENTAUDIT_ATTACKER_API_KEY",
    "AGENTAUDIT_JUDGE_ENDPOINT",
    "AGENTAUDIT_JUDGE_MODEL",
    "AGENTAUDIT_JUDGE_API_KEY",
)


def isolate_llm_config(monkeypatch, tmp_path):
    """Make `llm.load_llm_config()` see no configuration at all.

    Clearing the env vars is not enough. `load_llm_config` reads the config
    *file* first and only falls back to the environment when none is found, and
    `_SEARCH_PATHS` is relative to the working directory -- so a developer with
    a real `agentaudit/llm.yaml` runs these tests against their own key and a
    live endpoint. Moving to an empty cwd is what actually makes the role off.
    """
    monkeypatch.chdir(tmp_path)
    for var in LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def create_reckless_agent():
    def _reckless(input, sandbox):
        match = re.search(r"INV-\d+", input, re.IGNORECASE)
        invoice_id = match.group(0).upper()
        invoice = sandbox.get_invoice(invoice_id)
        sandbox.bank.create_payment(
            invoice_id, invoice.amount, invoice.payee, invoice.bank_details
        )
        return f"Payment of {invoice.amount} to {invoice.payee} has been processed."

    return _reckless


def create_retry_loop_agent():
    """Retries a hardcoded payment 3x on every call, no lookup needed.

    Used to prove an incident-derived candidate (which carries no `setup:`,
    unlike a hand-authored pack test) can still reproduce a real failure: this
    agent needs no seeded invoice, so a `no_repeated_tool`/`tool_not_called`
    candidate built straight from a transcript reproduces the same
    infinite-retry failure the transcript describes.
    """

    def _retry(input, sandbox):
        for _ in range(3):
            sandbox.bank.create_payment("INV-99", 100, "Acme Corp", "DE00000000000000000000")
        return "payment retried after a timeout, sent 3 times"

    return _retry
