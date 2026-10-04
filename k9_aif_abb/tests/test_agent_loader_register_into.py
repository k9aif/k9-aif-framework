# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""AgentLoader.register_into: agents registered by name from YAML (class + module)."""

import pytest

from k9_aif_abb.k9_agents.agent_loader import AgentLoader
from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry


def test_register_into_resolves_class_from_yaml(tmp_path):
    (tmp_path / "a.yaml").write_text("class: AgentLoader\nmodule: k9_aif_abb.k9_agents.agent_loader\nrole: x\n")
    loader = AgentLoader(tmp_path)
    assert loader.resolve_class("AgentLoader") is AgentLoader
    reg = AgentRegistry()
    loader.register_into(reg, {"inference": {}}, ["AgentLoader"])
    assert reg.exists("AgentLoader")


def test_missing_module_field_is_explicit(tmp_path):
    (tmp_path / "b.yaml").write_text("class: Nope\n")
    with pytest.raises(KeyError, match="module"):
        AgentLoader(tmp_path).resolve_class("Nope")
