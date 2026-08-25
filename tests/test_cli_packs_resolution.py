"""Pack-argument resolution: bare names work outside a clone, local paths win."""

from pathlib import Path

from agentaudit.cli import _resolve_packs_dir


def test_existing_local_path_is_returned_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "core").mkdir()
    assert _resolve_packs_dir("core") == "core"


def test_bare_name_resolves_to_shipped_pack(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTAUDIT_PACKS", raising=False)
    resolved = Path(_resolve_packs_dir("core"))
    assert resolved.is_dir()
    assert (resolved / "endpoint_contract").is_dir()


def test_repo_relative_prefix_resolves_to_shipped_pack(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTAUDIT_PACKS", raising=False)
    assert Path(_resolve_packs_dir("agentaudit/packs/core")).is_dir()


def test_subpath_is_preserved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTAUDIT_PACKS", raising=False)
    resolved = Path(_resolve_packs_dir("agentaudit/packs/core/endpoint_contract"))
    assert resolved.is_dir()
    assert resolved.name == "endpoint_contract"


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    packs = tmp_path / "elsewhere"
    (packs / "mypack").mkdir(parents=True)
    monkeypatch.setenv("AGENTAUDIT_PACKS", str(packs))
    assert Path(_resolve_packs_dir("mypack")) == packs / "mypack"


def test_unknown_name_is_returned_for_the_loader_to_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTAUDIT_PACKS", raising=False)
    assert _resolve_packs_dir("nope") == "nope"
