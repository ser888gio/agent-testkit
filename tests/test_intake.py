"""Run intake, tested as function calls.

Every case here used to need a TestClient, an authenticated principal and a
JSON round-trip, because the policy lived inside FastAPI route handlers. That
is the whole point of `core/intake.py`.
"""

from __future__ import annotations

import pytest

from agentaudit.core.intake import (
    IntakeError,
    first_party_hosts,
    first_party_secret_ref,
    is_offerable_target,
    narrow_selection,
    queue_run,
    register_http_target,
    resolve_target_and_pack,
    resolve_within_allowed,
)
from agentaudit.core.store import DEFAULT_ORG, Store

ORG = DEFAULT_ORG
AGENTIC_PACK = "agentaudit/packs/agentic"
TREASURY_TARGET = "agentaudit/config/treasury-agent.yaml"


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "intake.db"))
    yield s
    s.close()


@pytest.fixture
def imported_pack(store) -> str:
    """A pack imported into the org, as `queue_run` would leave it."""
    return resolve_target_and_pack(store, ORG, TREASURY_TARGET, AGENTIC_PACK)[1]


# --- path resolution --------------------------------------------------------


def test_resolve_within_allowed_is_cwd_independent(tmp_path, monkeypatch):
    """Prod runs from a CWD that is not the package parent; /connect-options
    hands back paths relative to the package parent either way."""
    monkeypatch.chdir(tmp_path)
    assert resolve_within_allowed(AGENTIC_PACK).is_dir()


@pytest.mark.parametrize(
    "value",
    [
        "../../../etc/passwd",
        "agentaudit/packs/../../setup.py",
        "/etc/passwd",
        "agentaudit/core/runner.py",
        "agentaudit/packs/does-not-exist",
    ],
)
def test_resolve_within_allowed_refuses_anything_outside_the_roots(value):
    """The allowlist is what stops intake loading an arbitrary Python callable."""
    with pytest.raises(IntakeError):
        resolve_within_allowed(value)


# --- registering a target ---------------------------------------------------


def test_register_seeds_the_allowlist_from_the_endpoint_host(store):
    """A target the tenant typed is only reachable at the host they typed."""
    register_http_target(store, ORG, target_id="mine", endpoint="https://agent.example.com/v1/chat")
    assert store.get_target_allowed_hosts(ORG, "mine") == ["agent.example.com"]


@pytest.mark.parametrize(
    "endpoint",
    ["ftp://agent.example.com", "not-a-url", "", "https://", "/relative/path"],
)
def test_register_refuses_an_endpoint_that_is_not_an_absolute_http_url(store, endpoint):
    with pytest.raises(IntakeError, match="absolute http"):
        register_http_target(store, ORG, target_id="mine", endpoint=endpoint)


def test_register_refuses_a_blank_target_id(store):
    with pytest.raises(IntakeError, match="Target id is required"):
        register_http_target(store, ORG, target_id="   ", endpoint="https://a.example.com")


def test_register_trims_whitespace_around_the_id_and_endpoint(store):
    target_id = register_http_target(
        store, ORG, target_id="  spaced  ", endpoint="  https://a.example.com/x  "
    )
    assert target_id == "spaced"
    assert store.get_target_allowed_hosts(ORG, "spaced") == ["a.example.com"]


def test_register_sends_the_prompt_as_a_json_body(store):
    """Without a request template the agent gets POSTed an empty body."""
    register_http_target(store, ORG, target_id="mine", endpoint="https://a.example.com")
    assert store.get_target(ORG, "mine")["agent"]["request"] == {
        "json": {"input": "{{ input }}"}
    }


def test_register_honours_a_custom_input_path(store):
    register_http_target(
        store, ORG, target_id="mine", endpoint="https://a.example.com", input_path="prompt"
    )
    assert store.get_target(ORG, "mine")["agent"]["request"] == {
        "json": {"prompt": "{{ input }}"}
    }


def test_register_is_org_scoped(store):
    register_http_target(store, "org-a", target_id="mine", endpoint="https://a.example.com")
    with pytest.raises(KeyError):
        store.get_target("org-b", "mine")


# --- first-party config helpers ---------------------------------------------


def test_a_single_env_ref_becomes_one_secret_ref():
    assert first_party_secret_ref({"headers": {"x": "${TOKEN}"}}) == "env://TOKEN"


def test_a_config_with_no_env_refs_needs_no_secret_ref():
    assert first_party_secret_ref({"agent": {"endpoint": "https://a.example.com"}}) is None


def test_several_env_refs_are_refused_rather_than_guessed():
    """Picking one of them would persist a target reachable with the wrong credential."""
    with pytest.raises(IntakeError, match="several secrets"):
        first_party_secret_ref({"a": "${ONE}", "b": "${TWO}"})


def test_first_party_hosts_reads_the_declared_endpoint():
    raw = {"agent": {"type": "http", "endpoint": "https://declared.example.com/v1"}}
    assert first_party_hosts(raw) == ["declared.example.com"]


def test_a_callable_target_has_no_host_to_allow():
    """None means 'no egress policy applies', which is not the same as an empty allowlist."""
    assert first_party_hosts({"agent": {"type": "callable", "callable": "m:f"}}) is None


# --- the demo-mode picker ---------------------------------------------------


def test_every_shipped_target_is_offerable_outside_demo_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTAUDIT_DEMO_MODE", raising=False)
    unreadable = tmp_path / "nope.yaml"
    assert is_offerable_target(unreadable)


def test_demo_mode_offers_only_in_process_targets(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTAUDIT_DEMO_MODE", "1")
    callable_cfg = tmp_path / "callable.yaml"
    callable_cfg.write_text("agent:\n  type: callable\n  callable: m:f\n", encoding="utf-8")
    http_cfg = tmp_path / "http.yaml"
    http_cfg.write_text(
        "agent:\n  type: http\n  endpoint: https://a.example.com\n", encoding="utf-8"
    )

    assert is_offerable_target(callable_cfg)
    # A shipped HTTP config points at a host that does not exist from a hosted
    # instance -- offering it would be a dead end in the picker.
    assert not is_offerable_target(http_cfg)


def test_demo_mode_hides_a_target_it_cannot_read(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTAUDIT_DEMO_MODE", "1")
    assert not is_offerable_target(tmp_path / "missing.yaml")


# --- selection --------------------------------------------------------------


def test_no_test_ids_means_the_whole_pack(store, imported_pack):
    assert narrow_selection(store, ORG, imported_pack, []) is None


def test_selecting_every_test_is_the_same_as_selecting_none(store, imported_pack):
    """Storing it as a selection would freeze the pack's current contents into the job."""
    every = [row["id"] for row in store.get_pack_tests(ORG, imported_pack)]
    assert narrow_selection(store, ORG, imported_pack, every) is None


def test_a_subset_is_kept_sorted(store, imported_pack):
    every = sorted(row["id"] for row in store.get_pack_tests(ORG, imported_pack))
    assert len(every) >= 2
    assert narrow_selection(store, ORG, imported_pack, [every[1], every[0]]) == [every[0], every[1]]


def test_test_ids_are_checked_against_the_pack_not_trusted(store, imported_pack):
    """The client supplies these; an id from another pack must not be queued."""
    with pytest.raises(IntakeError, match="unknown test"):
        narrow_selection(store, ORG, imported_pack, ["not.a.real.test"])


# --- queueing ---------------------------------------------------------------


def test_queue_run_imports_the_rows_the_worker_will_read(store):
    """The worker resolves jobs from the database only, so rows must exist first."""
    job_id = queue_run(
        store,
        ORG,
        target=TREASURY_TARGET,
        packs=AGENTIC_PACK,
        created_by="someone",
    )
    job = store.jobs.get(ORG, job_id)
    assert store.get_target(ORG, job.target_id)
    assert store.get_pack_tests(ORG, job.pack_id)
    assert job.created_by == "someone"


def test_queue_run_against_a_registered_target_needs_no_shipped_config(store):
    """A registered target's row already exists; only the pack needs importing."""
    register_http_target(store, ORG, target_id="mine", endpoint="https://a.example.com/v1")
    job_id = queue_run(store, ORG, target="mine", packs=AGENTIC_PACK)
    assert store.jobs.get(ORG, job_id).target_id == "mine"


def test_an_unknown_target_names_itself_in_the_error(store):
    with pytest.raises(IntakeError, match="unknown target 'nope'"):
        queue_run(store, ORG, target="nope", packs=AGENTIC_PACK)


def test_queue_run_is_idempotent_in_its_imports(store):
    """Re-running the same target and pack must not accumulate rows."""
    for _ in range(2):
        queue_run(store, ORG, target=TREASURY_TARGET, packs=AGENTIC_PACK)
    assert len(store.list_targets(ORG)) == 1
    assert len(store.list_packs(ORG)) == 1
