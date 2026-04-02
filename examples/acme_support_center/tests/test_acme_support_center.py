# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from examples.acme_support_center.orchestrators.support_orchestrator import SupportOrchestrator


def test_orchestrator_instantiates():
    orch = SupportOrchestrator({})
    assert orch is not None