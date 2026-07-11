# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — tests for ABB AgentLoader

import pytest
import yaml
from pathlib import Path

from k9_aif_abb.k9_agents.agent_loader import AgentLoader, _get_nested, _set_nested


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_agent_yaml(tmp_path: Path, class_name: str, extra: dict = None) -> None:
    data = {"class": class_name, "role": f"You are {class_name}", "model": "reasoning"}
    if extra:
        data.update(extra)
    (tmp_path / f"{class_name}.yaml").write_text(yaml.dump(data))


# ---------------------------------------------------------------------------
# Dot-notation helpers
# ---------------------------------------------------------------------------

def test_get_nested_flat():
    assert _get_nested({"a": 1}, "a") == 1


def test_get_nested_deep():
    assert _get_nested({"a": {"b": {"c": 42}}}, "a.b.c") == 42


def test_get_nested_missing():
    assert _get_nested({"a": 1}, "a.b") is None


def test_set_nested_flat():
    d = {}
    _set_nested(d, "x", 99)
    assert d == {"x": 99}


def test_set_nested_deep():
    d = {}
    _set_nested(d, "a.b.c", "hello")
    assert d["a"]["b"]["c"] == "hello"


# ---------------------------------------------------------------------------
# AgentLoader basics
# ---------------------------------------------------------------------------

def test_load_agent_yaml(tmp_path):
    _write_agent_yaml(tmp_path, "MyAgent")
    loader = AgentLoader(tmp_path)
    assert loader.has_agent("MyAgent")
    assert loader.get_agent_yaml("MyAgent")["role"] == "You are MyAgent"


def test_missing_class_field_skipped(tmp_path):
    (tmp_path / "bad.yaml").write_text(yaml.dump({"role": "no class here"}))
    loader = AgentLoader(tmp_path)
    assert loader.list_classes() == []


def test_missing_yaml_dir(tmp_path):
    loader = AgentLoader(tmp_path / "does_not_exist")
    assert loader.list_classes() == []


def test_list_classes(tmp_path):
    _write_agent_yaml(tmp_path, "AgentA")
    _write_agent_yaml(tmp_path, "AgentB")
    loader = AgentLoader(tmp_path)
    assert set(loader.list_classes()) == {"AgentA", "AgentB"}


# ---------------------------------------------------------------------------
# merge_with_global — normal behaviour
# ---------------------------------------------------------------------------

def test_merge_agent_yaml_wins_on_collision(tmp_path):
    _write_agent_yaml(tmp_path, "MyAgent", {"model": "agent_model"})
    loader = AgentLoader(tmp_path)
    merged = loader.merge_with_global("MyAgent", {"model": "global_model", "inference": {}})
    assert merged["model"] == "agent_model"


def test_merge_global_fills_missing_keys(tmp_path):
    _write_agent_yaml(tmp_path, "MyAgent")
    loader = AgentLoader(tmp_path)
    merged = loader.merge_with_global("MyAgent", {"inference": {"provider": "ollama"}})
    assert merged["inference"]["provider"] == "ollama"


def test_merge_unknown_agent_returns_global(tmp_path):
    loader = AgentLoader(tmp_path)
    global_cfg = {"inference": {}, "messaging": {}}
    assert loader.merge_with_global("GhostAgent", global_cfg) == global_cfg


def test_policy_block_stripped_from_result(tmp_path):
    _write_agent_yaml(tmp_path, "MyAgent")
    loader = AgentLoader(tmp_path)
    global_cfg = {"_policy": {"locked": []}, "model": "global"}
    merged = loader.merge_with_global("MyAgent", global_cfg)
    assert "_policy" not in merged


# ---------------------------------------------------------------------------
# _policy.locked enforcement
# ---------------------------------------------------------------------------

def test_locked_flat_key_not_overridden(tmp_path):
    _write_agent_yaml(tmp_path, "MyAgent", {"enable_zero_trust": False})
    loader = AgentLoader(tmp_path)
    global_cfg = {
        "_policy": {"locked": ["enable_zero_trust"]},
        "enable_zero_trust": True,
    }
    merged = loader.merge_with_global("MyAgent", global_cfg)
    assert merged["enable_zero_trust"] is True


def test_locked_nested_key_not_overridden(tmp_path):
    _write_agent_yaml(tmp_path, "MyAgent", {"security": {"shield": {"enabled": False}}})
    loader = AgentLoader(tmp_path)
    global_cfg = {
        "_policy": {"locked": ["security.shield.enabled"]},
        "security": {"shield": {"enabled": True}},
    }
    merged = loader.merge_with_global("MyAgent", global_cfg)
    assert merged["security"]["shield"]["enabled"] is True


def test_unlocked_key_can_be_overridden(tmp_path):
    _write_agent_yaml(tmp_path, "MyAgent", {"model": "sbb_model"})
    loader = AgentLoader(tmp_path)
    global_cfg = {
        "_policy": {"locked": ["enable_zero_trust"]},
        "model": "global_model",
        "enable_zero_trust": True,
    }
    merged = loader.merge_with_global("MyAgent", global_cfg)
    assert merged["model"] == "sbb_model"
    assert merged["enable_zero_trust"] is True


def test_locked_key_not_attempted_override_no_warning(tmp_path, caplog):
    _write_agent_yaml(tmp_path, "MyAgent")
    loader = AgentLoader(tmp_path)
    global_cfg = {
        "_policy": {"locked": ["enable_zero_trust"]},
        "enable_zero_trust": True,
    }
    import logging
    with caplog.at_level(logging.WARNING):
        loader.merge_with_global("MyAgent", global_cfg)
    assert "POLICY" not in caplog.text


def test_locked_key_override_attempt_logs_warning(tmp_path, caplog):
    _write_agent_yaml(tmp_path, "MyAgent", {"enable_zero_trust": False})
    loader = AgentLoader(tmp_path)
    global_cfg = {
        "_policy": {"locked": ["enable_zero_trust"]},
        "enable_zero_trust": True,
    }
    import logging
    with caplog.at_level(logging.WARNING):
        loader.merge_with_global("MyAgent", global_cfg)
    assert "POLICY" in caplog.text
    assert "enable_zero_trust" in caplog.text


def test_empty_locked_list_no_enforcement(tmp_path):
    _write_agent_yaml(tmp_path, "MyAgent", {"enable_zero_trust": False})
    loader = AgentLoader(tmp_path)
    global_cfg = {"_policy": {"locked": []}, "enable_zero_trust": True}
    merged = loader.merge_with_global("MyAgent", global_cfg)
    assert merged["enable_zero_trust"] is False


def test_no_policy_block_behaves_as_before(tmp_path):
    _write_agent_yaml(tmp_path, "MyAgent", {"model": "sbb_model"})
    loader = AgentLoader(tmp_path)
    merged = loader.merge_with_global("MyAgent", {"model": "global_model"})
    assert merged["model"] == "sbb_model"
