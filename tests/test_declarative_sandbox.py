"""Toolkit YAML loading and the generic Sandbox it drives, independent of any
specific vertical's demo agents (see tests/test_support.py for the worked
example end to end).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from agentaudit.core.sandbox import SANDBOXES, build_sandbox
from agentaudit.domains.declarative.sandbox import DeclarativeSandbox, Ledger, Mailbox
from agentaudit.domains.declarative.toolkit import (
    ToolkitError,
    discover_toolkits,
    load_toolkit_file,
)


def test_support_toolkit_registers_at_import_time():
    assert "support" in SANDBOXES
    sb = build_sandbox("support")
    assert isinstance(sb, DeclarativeSandbox)
    assert sb.name == "support"


def test_ledger_seed_then_create_tracks_only_post_setup_creates():
    sb = build_sandbox("support")
    sb.apply_setup({"tickets": [{"id": "TCK-1", "approved": True}]})
    ledger = sb.ledger("tickets")
    assert ledger.no_record_created("TCK-1")  # seeded, not "created" by the agent

    ledger.create("TCK-2", approved=False)
    assert ledger.created_count("TCK-2") == 1
    assert not ledger.no_record_created("TCK-2")
    assert ledger.created_count() == 1


def test_ledger_update_is_tracked_and_visible_in_diff():
    sb = build_sandbox("support")
    sb.apply_setup({"tickets": [{"id": "TCK-1", "refunded": False}]})
    before = sb.snapshot()
    sb.ledger("tickets").update("TCK-1", refunded=True)
    after = sb.snapshot()
    diff = sb.diff(before, after)
    assert "tickets" in diff["changed"]


def test_mailbox_send_and_external_check():
    sb = build_sandbox("support")
    mailbox = sb.mailbox("notifications")
    assert mailbox.no_message_to("a@customer.example")
    mailbox.send(to="a@customer.example", subject="hi")
    assert mailbox.message_count("a@customer.example") == 1
    assert not mailbox.no_message_to("a@customer.example")
    assert mailbox.is_external("a@customer.example")

    mailbox.contacts = {"known@acme-support.example"}
    assert not mailbox.is_external("known@acme-support.example")
    assert not mailbox.is_external("agent@acme-support.example")  # internal domain


def test_reset_clears_resources_and_events():
    sb = build_sandbox("support")
    sb.ledger("tickets").create("TCK-1", approved=True)
    sb.mailbox("notifications").send(to="x@y.example")
    sb.reset()
    assert sb.snapshot()["tickets"]["records"] == {}
    assert sb.snapshot()["notifications"]["sent"] == []
    assert sb.events == []


def test_snapshot_is_json_serializable():
    import json

    sb = build_sandbox("support")
    sb.apply_setup({"tickets": [{"id": "TCK-1", "approved": True}]})
    sb.ledger("tickets").update("TCK-1", refunded=True)
    sb.mailbox("notifications").send(to="a@customer.example", subject="hi")
    json.dumps(sb.snapshot())  # must not raise


def test_apply_setup_unknown_key_raises():
    sb = build_sandbox("support")
    with pytest.raises(ValueError, match="cannot apply setup key 'bogus'"):
        sb.apply_setup({"bogus": 1})


def test_ledger_accessor_type_mismatch_raises():
    sb = build_sandbox("support")
    with pytest.raises(TypeError, match="is not a mailbox"):
        sb.mailbox("tickets")
    with pytest.raises(TypeError, match="is not a ledger"):
        sb.ledger("notifications")


def test_ledger_and_mailbox_helper_classes_stand_alone():
    sb = build_sandbox("support")
    ledger = Ledger(sb, "tickets")
    ledger.seed([{"id": "T1", "amount": 5}])
    assert ledger.get("T1") == {"id": "T1", "amount": 5}

    mailbox = Mailbox(sb, "notifications", internal_domain="corp.example")
    mailbox.send(to="ext@other.example")
    assert mailbox.message_count() == 1


# --- toolkit.py -------------------------------------------------------------


def test_load_toolkit_file_parses_resources(tmp_path):
    path = tmp_path / "widget.yaml"
    path.write_text(
        "name: widget\n"
        "resources:\n"
        "  - kind: ledger\n"
        "    name: orders\n"
        "    fields: [id, status]\n"
        "  - kind: mailbox\n"
        "    name: outbox\n"
        "    internal_domain: widget.example\n",
        encoding="utf-8",
    )
    decl = load_toolkit_file(path)
    assert decl.name == "widget"
    assert decl.resource("orders").kind == "ledger"
    assert decl.resource("outbox").internal_domain == "widget.example"
    assert decl.resources_of_kind("ledger") == [decl.resource("orders")]


def test_load_toolkit_file_missing_name_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("resources: [{kind: ledger, name: x}]\n", encoding="utf-8")
    with pytest.raises(ToolkitError, match="missing a top-level 'name'"):
        load_toolkit_file(path)


def test_load_toolkit_file_no_resources_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\nresources: []\n", encoding="utf-8")
    with pytest.raises(ToolkitError, match="at least one resource"):
        load_toolkit_file(path)


def test_load_toolkit_file_unsupported_kind_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\nresources: [{kind: queue, name: x}]\n", encoding="utf-8")
    with pytest.raises(ToolkitError, match="unsupported resource kind 'queue'"):
        load_toolkit_file(path)


def test_load_toolkit_file_duplicate_resource_names_raise(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\n"
        "resources:\n"
        "  - kind: ledger\n    name: x\n"
        "  - kind: mailbox\n    name: x\n",
        encoding="utf-8",
    )
    with pytest.raises(ToolkitError, match="must be unique"):
        load_toolkit_file(path)


def test_discover_toolkits_returns_empty_for_missing_dir(tmp_path):
    assert discover_toolkits(tmp_path / "does-not-exist") == []


def test_the_registry_loads_declarative_sandboxes_in_a_fresh_interpreter():
    """A fresh interpreter that never imported a domain still sees `support`.

    Same reasoning as `test_sandbox_core.py`'s equivalent: the isolation
    supervisor's spawned child imports sandbox modules by name
    (`sandbox_modules()`), so registration must survive a bare re-import, not
    just work when something else already populated the registry in-process.
    """
    code = (
        "from agentaudit.core.sandbox import build_sandbox, sandbox_modules;"
        "print(build_sandbox('support').name);"
        "print(','.join(sandbox_modules()))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    name, modules = proc.stdout.split()
    assert name == "support"
    assert "agentaudit.domains.declarative.sandbox" in modules.split(",")
