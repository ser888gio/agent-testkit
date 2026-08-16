import inspect

import pytest

from agentkit.core.artifacts import ArtifactKeyError, artifact_key
from agentkit.core.store import Store
from tests.test_web import _seed_store


def test_key_is_org_run_artifact():
    assert artifact_key("org-a", "run-1", "trace.json") == "org-a/run-1/trace.json"


def test_key_cannot_be_built_without_an_org():
    signature = inspect.signature(artifact_key)
    org = signature.parameters["org_id"]
    assert org.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        artifact_key(run_id="run-1", artifact_id="trace.json")


@pytest.mark.parametrize(
    "bad",
    [
        "..",
        "../etc/passwd",
        "a/../../b",
        "sub/dir",
        "sub\\dir",
        "/absolute",
        "C:/windows",
        "",
        " padded ",
        ".hidden",
    ],
)
@pytest.mark.parametrize("position", ["org_id", "run_id", "artifact_id"])
def test_key_rejects_escaping_components(bad, position):
    parts = {"org_id": "org-a", "run_id": "run-1", "artifact_id": "trace.json"}
    parts[position] = bad
    with pytest.raises(ArtifactKeyError):
        artifact_key(**parts)


def test_key_rejects_a_non_string_component():
    with pytest.raises(ArtifactKeyError):
        artifact_key("org-a", "run-1", None)


def test_save_artifact_derives_the_path_and_scopes_reads(tmp_path):
    db = str(tmp_path / "artifacts.db")
    _cfg, rr, _report = _seed_store(db)
    store = Store(db)

    path = store.save_artifact("default", rr.run_id, "trace.json", "application/json", 12)

    assert path == f"default/{rr.run_id}/trace.json"
    assert store.get_artifact("default", "trace.json").path == path
    assert len(store.list_artifacts("default", rr.run_id)) == 1

    with pytest.raises(KeyError):
        store.get_artifact("org-b", "trace.json")
    assert store.list_artifacts("org-b", rr.run_id) == []


def test_save_artifact_rejects_a_run_from_another_org(tmp_path):
    db = str(tmp_path / "foreign.db")
    _cfg, rr, _report = _seed_store(db)
    store = Store(db)

    with pytest.raises(KeyError):
        store.save_artifact("org-b", rr.run_id, "trace.json", "application/json", 12)


def test_save_artifact_rejects_a_traversing_id(tmp_path):
    db = str(tmp_path / "traverse.db")
    _cfg, rr, _report = _seed_store(db)
    store = Store(db)

    with pytest.raises(ArtifactKeyError):
        store.save_artifact("default", rr.run_id, "../../escape", "application/json", 1)
    assert store.list_artifacts("default", rr.run_id) == []
