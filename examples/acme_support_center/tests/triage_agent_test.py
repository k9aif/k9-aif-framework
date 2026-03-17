# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from examples.acme_support_center.agents.triage_agent import TriageAgent

class MockTicketTool:
    def run(self, payload):
        return {"ticket_found": False, "message": "No existing ticket found."}

agent = TriageAgent(
    config={
        "description": "Initial triage and classification of support requests",
        "pattern": "react",
        "model": "general",
        "config": {"max_iterations": 3},
    },
    tools={
        "ticket_tool": MockTicketTool(),
    },
)

result = agent.run("My login is not working and this is urgent.")
print(result)