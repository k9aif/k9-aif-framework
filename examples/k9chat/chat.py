# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import os
import sys
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from k9_aif_abb.k9_squad.squad_loader import SquadLoader
from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry
from k9_aif_abb.k9_orchestrators.registry.orchestrator_registry import OrchestratorRegistry
from k9_aif_abb.k9_orchestrators.framework_orchestrator import FrameworkOrchestrator
from examples.k9chat.chat_agent import ChatAgent


BASE_DIR = os.path.dirname(__file__)


def main():

    with open(os.path.join(BASE_DIR, "config.yaml")) as f:
        config = yaml.safe_load(f)

    agent_registry = AgentRegistry()
    agent_registry.register("chat_agent", ChatAgent)

    orchestrator_registry = OrchestratorRegistry()
    orchestrator_registry.register("framework", FrameworkOrchestrator)

    loader = SquadLoader(agent_registry, orchestrator_registry)
    squads = loader.load(os.path.join(BASE_DIR, "squad.yaml"))

    squad = squads["k9chat"]
    agent = squad.agents[0]

    print("\nK9Chat ready\n")

    while True:
        prompt = input("> ")

        if prompt.lower() in ["exit", "quit"]:
            break

        result = agent.execute({"text": prompt})

        print("\n", result["text"], "\n")


if __name__ == "__main__":
    main()