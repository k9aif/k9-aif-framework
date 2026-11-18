# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""An agent YAML that does not parse is named in the error for the class it should have provided (no silent skip)."""

import pytest

from k9_aif_abb.k9_agents.agent_loader import AgentLoader


def test_missing_class_error_names_the_unreadable_file(tmp_path):
    (tmp_path / "payment_agent.yaml").write_text("class: PaymentAgent\ninstructions:\n  - paid: say\n    more\n")
    loader = AgentLoader(tmp_path)
    with pytest.raises(KeyError) as exc:
        loader.resolve_class("PaymentAgent")
    assert "payment_agent.yaml could not be loaded" in str(exc.value)
