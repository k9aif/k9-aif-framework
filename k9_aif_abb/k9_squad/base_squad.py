# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from .squad_context import SquadContext


class BaseSquad:
    """
    ABB: Represents a coordinated team of agents
    working together for a capability or use case.
    """

    def __init__(self, squad_id, agents, orchestrator, monitor=None):
        self.squad_id = squad_id
        self.agents = agents or []
        self.orchestrator = orchestrator
        self.monitor = monitor
        self.description = ""
        self.flow = []
        self.metadata = {}

    def run(self, payload):
        context = SquadContext(payload)

        if self.monitor:
            self.monitor.on_squad_start(self.squad_id)

        result = self.orchestrator.execute(self, context)

        if self.monitor:
            self.monitor.on_squad_end(self.squad_id)

        return result