"""
CrewAI orchestrator adapter for K9-AIF.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class CrewAIOrchestratorAdapter:
    """
    Thin adapter that wraps a CrewAI crew object and exposes a K9-AIF-friendly execution method.
    """

    def __init__(self, crew: Any, name: Optional[str] = None) -> None:
        self.crew = crew
        self.name = name or "CrewAIOrchestratorAdapter"

    def execute(self, crew_input: Dict[str, Any]) -> Any:
        """
        Execute the underlying CrewAI crew.

        Tries common CrewAI invocation styles conservatively.
        """
        if self.crew is None:
            raise ValueError("CrewAI crew is not configured.")

        # Common CrewAI pattern
        if hasattr(self.crew, "kickoff"):
            return self.crew.kickoff(inputs=crew_input)

        # Fallbacks for alternate wrapper styles
        if hasattr(self.crew, "run"):
            return self.crew.run(crew_input)

        raise AttributeError(
            f"{self.name} could not find a supported execution method on the provided crew."
        )