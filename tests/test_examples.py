"""Smoke tests for examples/: target configs parse, pack-style YAML stays valid.

The examples exist so a new user can copy-paste them; if they rot, they are
worse than no examples. These tests fail offline on any malformed YAML, invalid
target config, or unknown assertion name without touching the network.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agentaudit.core.assertions import REGISTRY as ASSERTION_REGISTRY
from agentaudit.core.config import load_target_dict

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def _example_yaml_paths() -> list[Path]:
    return sorted(EXAMPLES_DIR.rglob("*.yaml")) + sorted(EXAMPLES_DIR.rglob("*.yml"))


def test_examples_exist() -> None:
    paths = _example_yaml_paths()
    assert EXAMPLES_DIR.is_dir()
    assert len(paths) >= 3


def test_every_example_yaml_is_a_valid_target_or_pack_file() -> None:
    """Each YAML must be either a loadable TargetConfig or valid pack content."""
    assert _example_yaml_paths(), "no example YAML found"
    for path in _example_yaml_paths():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(raw, dict), f"{path}: expected a mapping"

        is_target = "agent" in raw
        is_pack_test = "assertions" in raw
        assert is_target or is_pack_test, (
            f"{path}: not recognizable as a target config ('agent') "
            f"or pack test ('assertions')"
        )
        if is_target:
            # ${VAR} references resolve from a fixed mapping, not the real
            # environment: the smoke test stays offline and deterministic.
            cfg = load_target_dict(
                raw,
                source=str(path),
                secrets={"AGENT_TOKEN": "smoke-test-token"},
            )
            assert cfg.id, f"{path}: target config has an empty id"


def test_no_example_references_unknown_assertions() -> None:
    checked = 0
    for path in _example_yaml_paths():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "assertions" not in raw:
            continue
        for assertion in raw["assertions"]:
            name = assertion.get("name")
            assert name in ASSERTION_REGISTRY, (
                f"{path}: unknown assertion '{name}'"
                f" (valid: {', '.join(sorted(ASSERTION_REGISTRY))})"
            )
            checked += 1
    # The treasury example ships pack-shaped scenarios; if none were seen here,
    # the registry cross-check above proved nothing.
    assert checked > 0


def test_example_readmes_exist_and_name_their_commands() -> None:
    for folder in ("http-endpoint", "treasury-demo", "external-redteam"):
        readme = EXAMPLES_DIR / folder / "README.md"
        assert readme.is_file(), f"{readme} missing"
        text = readme.read_text(encoding="utf-8")
        assert "agentaudit run" in text, f"{readme} never shows an agentaudit command"
