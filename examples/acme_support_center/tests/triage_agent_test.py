# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from examples.acme_support_center.agents.src.triage_agent import TriageAgent


class MockTicketTool:
    def run(self, payload):
        return {"ticket_found": False, "message": "No existing ticket found."}


agent = TriageAgent(
    config={
        "description": "Initial triage and classification of support requests",
        "pattern": "react",
        "model": "general",
        "config": {"max_iterations": 3},
        "inference": {
            "llm_factory": {
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "models": {
                    "general": "llama3.2:1b"
                },
            }
        },
    },
    tools={
        "ticket_tool": MockTicketTool(),
    },
)

result = agent.run("My login is not working and this is urgent.")
print(result)