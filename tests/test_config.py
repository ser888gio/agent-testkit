from pathlib import Path

import pytest
import yaml

from agentkit.core.config import ConfigError, load_target, load_target_dict

TREASURY_CALLABLE_YAML = "agentkit/config/treasury-agent.yaml"
TREASURY_HTTP_YAML = "agentkit/config/treasury-http.yaml"


def test_load_callable_target():
    cfg = load_target(TREASURY_CALLABLE_YAML)
    assert cfg.id == "treasury-demo"
    assert cfg.agent.type == "callable"
    assert cfg.agent.callable == "agentkit.domains.treasury.agent:create_agent"
    assert cfg.sandbox == "treasury"
    assert cfg.evidence.store_request is True


def test_load_http_target_interpolates_env(monkeypatch):
    monkeypatch.setenv("AGENT_TOKEN", "secret-token")
    cfg = load_target(TREASURY_HTTP_YAML)
    assert cfg.id == "treasury-http"
    assert cfg.agent.type == "http"
    assert cfg.agent.endpoint == "http://localhost:8001/run"
    assert cfg.agent.headers["Authorization"] == "Bearer secret-token"
    # {{ input }} placeholder left intact for HTTPAgent to render
    assert cfg.agent.request["json"]["input"] == "{{ input }}"


def test_missing_env_var_raises(monkeypatch):
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="AGENT_TOKEN"):
        load_target(TREASURY_HTTP_YAML)


def test_http_spec_missing_endpoint_raises(tmp_path):
    bad = tmp_path / "bad-http.yaml"
    bad.write_text(
        "id: bad-http\nagent:\n  type: http\nsandbox: treasury\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="requires endpoint"):
        load_target(bad)


def test_unknown_sandbox_raises(tmp_path):
    bad = tmp_path / "bad-sandbox.yaml"
    bad.write_text(
        "id: bad-sandbox\n"
        "agent:\n  type: callable\n  callable: mod:factory\n"
        "sandbox: not-a-real-sandbox\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="valid sandboxes"):
        load_target(bad)


@pytest.mark.parametrize("path", sorted(Path("agentkit/config").glob("*.yaml")))
def test_file_and_dict_loaders_match_for_all_shipped_configs(path, monkeypatch):
    monkeypatch.setenv("AGENT_TOKEN", "test-token")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert load_target(path) == load_target_dict(raw, source=str(path))


@pytest.mark.parametrize("agent", ["http", ["http"]])
def test_non_mapping_agent_raises_config_error(agent):
    with pytest.raises(ConfigError, match="agent.*mapping"):
        load_target_dict({"id": "bad-agent", "agent": agent})
