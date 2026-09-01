"""LLM config loading, key resolution, and the credential-literal refusal."""

from __future__ import annotations

import pytest

from agentaudit.core import llm


def write(tmp_path, text: str):
    path = tmp_path / "llm.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_both_roles(tmp_path, monkeypatch):
    path = write(
        tmp_path,
        """
attacker:
  model: gpt-4o-mini
  api_key_ref: env://MY_KEY
judge:
  model: judge-model
  endpoint: http://localhost:11434/v1/chat/completions
""",
    )
    monkeypatch.setenv("MY_KEY", "sk-live-value")
    config = llm.load_llm_config(path)

    assert config.attacker.model == "gpt-4o-mini"
    assert config.attacker.endpoint == llm.DEFAULT_ENDPOINT
    assert config.attacker.api_key() == "sk-live-value"
    # No ref, no key: an unauthenticated local endpoint is legitimate.
    assert config.judge.api_key() is None


def test_missing_role_is_off(tmp_path):
    assert llm.load_llm_config(write(tmp_path, "attacker:\n  model: m\n")).judge is None


def test_refuses_a_pasted_key(tmp_path):
    path = write(tmp_path, "attacker:\n  model: m\n  api_key_ref: sk-abcdefgh12345\n")
    with pytest.raises(llm.LLMConfigError, match="credential literal"):
        llm.load_llm_config(path)


def test_rejects_unknown_ref_scheme(tmp_path):
    path = write(tmp_path, "attacker:\n  model: m\n  api_key_ref: vault://x\n")
    with pytest.raises(llm.LLMConfigError, match="scheme"):
        llm.load_llm_config(path)


@pytest.mark.parametrize("ref", ["env://VAR", "${VAR}", "VAR"])
def test_key_ref_spellings(ref, monkeypatch):
    monkeypatch.setenv("VAR", "v")
    assert llm.RoleConfig(model="m", api_key_ref=ref).api_key() == "v"


def test_falls_back_to_legacy_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTAUDIT_LLM_CONFIG", raising=False)
    monkeypatch.setenv("AGENTAUDIT_ATTACKER_ENDPOINT", "http://a/v1/chat/completions")
    monkeypatch.setenv("AGENTAUDIT_ATTACKER_MODEL", "m")
    monkeypatch.setenv("AGENTAUDIT_ATTACKER_API_KEY", "k")

    config = llm.load_llm_config()
    assert config.attacker.api_key() == "k"
    assert config.judge is None


def test_no_config_means_both_roles_off(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for var in (
        "AGENTAUDIT_LLM_CONFIG",
        "AGENTAUDIT_ATTACKER_ENDPOINT",
        "AGENTAUDIT_ATTACKER_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    config = llm.load_llm_config()
    assert config.attacker is None and config.judge is None


def test_build_client_applies_role_temperature(monkeypatch):
    monkeypatch.setenv("K", "secret")
    role = llm.RoleConfig(model="m", api_key_ref="env://K", temperature=0.2)
    client = llm.build_client(role, default_temperature=0.9)
    assert client.temperature == 0.2
    assert client.api_key == "secret"
    # The default applies only when the role does not set one.
    assert llm.build_client(llm.RoleConfig(model="m"), default_temperature=0.0).temperature == 0.0
    assert llm.build_client(None, default_temperature=0.0) is None


def test_describe_never_returns_the_key(monkeypatch, tmp_path):
    path = write(tmp_path, "attacker:\n  model: m\n  api_key_ref: env://SHOWN\n")
    monkeypatch.setenv("AGENTAUDIT_LLM_CONFIG", str(path))
    monkeypatch.setenv("SHOWN", "sk-do-not-leak")

    described = llm.describe()
    assert "sk-do-not-leak" not in repr(described)
    assert described["attacker"]["api_key_env"] == "SHOWN"
    assert described["attacker"]["api_key_present"] is True
    assert described["judge"] == {"configured": False}


def test_override_wins_over_file_and_restores(monkeypatch, tmp_path):
    path = write(tmp_path, "attacker:\n  model: from-file\n")
    monkeypatch.setenv("AGENTAUDIT_LLM_CONFIG", str(path))
    tenant = llm.LLMConfig(attacker=llm.RoleConfig(model="from-tenant"))

    with llm.override(tenant):
        assert llm.load_llm_config().attacker.model == "from-tenant"
    assert llm.load_llm_config().attacker.model == "from-file"


def test_tenant_key_literal_is_used_but_a_file_may_not_set_one(monkeypatch, tmp_path):
    monkeypatch.delenv("K", raising=False)
    role = llm.RoleConfig(model="m", api_key_ref="env://K", api_key_literal="sk-tenant")
    assert role.api_key() == "sk-tenant"

    path = write(tmp_path, "attacker:\n  model: m\n  api_key_literal: sk-nope\n")
    with pytest.raises(llm.LLMConfigError, match="api_key_literal"):
        llm.load_llm_config(path)
