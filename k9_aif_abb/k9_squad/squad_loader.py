# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .base_squad import BaseSquad, synthesis_config
from .squad_monitor import DefaultSquadMonitor


class SquadLoader:
    """
    Loads K9-AIF squad definitions from YAML and builds BaseSquad objects.

    Squads are decoupled from orchestrators — squad YAML lists only agents
    and flow steps. The orchestrator that loads a squad owns the association;
    it is never stored in the squad YAML.

    **The orchestrator knows only squads (1.18.1).** The agents a squad needs
    are named in its own YAML, so the squad layer builds them — never the
    orchestrator. Build the loader once at the application entry point and
    hand it to the orchestrators::

        # entry point
        squads = SquadLoader.from_agents(agents_yaml_dir, config=config)
        orch = MyOrchestrator(config=config, squads=squads)

        # inside the orchestrator: squad file and squad id only
        squad = self.squads.load_one(squads_dir / "claims_squad.yaml", "ClaimsSquad")

    ``from_agents`` resolves each agent named in the squad YAML through
    ``AgentLoader`` (``class:`` + ``module:`` in the agent YAML) and builds it
    with its merged config. If a squad's agents change, only the squad YAML
    (and the agent's own YAML and class) change; the orchestrator is unaffected.
    ``load_one(..., config=...)`` builds the agents with a per-run config (for
    example a governance override); ``squad_cls`` builds a solution's own
    ``BaseSquad`` subclass for squad-level behaviour (see ``BaseSquad.before_step``).

    A pre-filled ``agent_registry`` (``create(name)`` / ``get(name)``) still
    works; register it at the entry point, never inside an orchestrator.

    Expected YAML shape:

    squads:
      claims_intake:
        description: Example claims intake squad
        agents:
          - IntakeAgent
          - ExtractionAgent
          - ValidationAgent
        flow:
          - agent: IntakeAgent
            result_key: intake
          - agent: ExtractionAgent
            result_key: extraction
          - agent: ValidationAgent
            result_key: validation
    """

    def __init__(self, agent_registry=None, orchestrator_registry=None, monitor_cls=DefaultSquadMonitor,
                 *, agent_loader=None, config: Optional[Dict[str, Any]] = None,
                 agent_kwargs: Optional[Dict[str, Any]] = None, squad_cls=None):
        """
        Args:
            agent_registry:
                Registry object that supports either:
                  - create(name)
                  - get(name) -> class
                Not needed when ``agent_loader`` is given (see ``from_agents``).
            orchestrator_registry:
                Ignored — retained for backwards compatibility only.
                Orchestrator association is managed by the calling orchestrator,
                not stored in squad YAML.
            monitor_cls:
                Monitor class to attach by default to each squad.
            agent_loader:
                An ``AgentLoader``: agents named in the squad YAML are resolved
                and built through it (1.18.1).
            config:
                Global config the agents' own YAML is merged with.
            agent_kwargs:
                Extra keyword arguments for every agent constructor (e.g. ``monitor``).
            squad_cls:
                ``BaseSquad`` subclass to build (default ``BaseSquad``).
        """
        if agent_registry is None and agent_loader is None:
            raise ValueError("SquadLoader needs an agent_loader (SquadLoader.from_agents) or an agent_registry")
        self.agent_registry = agent_registry
        self.agent_loader = agent_loader
        self.config = config or {}
        self.agent_kwargs = dict(agent_kwargs or {})
        self.squad_cls = squad_cls or BaseSquad
        self.monitor_cls = monitor_cls

    @classmethod
    def from_agents(cls, agents_dir: str | Path, config: Optional[Dict[str, Any]] = None, *,
                    agent_kwargs: Optional[Dict[str, Any]] = None, squad_cls=None,
                    monitor_cls=DefaultSquadMonitor) -> "SquadLoader":
        """A loader that builds each squad's agents from the agent YAML in ``agents_dir``."""
        from k9_aif_abb.k9_agents.agent_loader import AgentLoader
        return cls(agent_loader=AgentLoader(agents_dir), config=config, agent_kwargs=agent_kwargs,
                   squad_cls=squad_cls, monitor_cls=monitor_cls)

    def load(self, path: str | Path, config: Optional[Dict[str, Any]] = None,
             agent_kwargs: Optional[Dict[str, Any]] = None) -> Dict[str, BaseSquad]:
        """
        Load all squads from a YAML file.

        ``config`` / ``agent_kwargs`` override the loader's own for the agents
        built by this call (e.g. a per-run governance override, a per-run monitor).

        Returns:
            Dict[str, BaseSquad]: mapping of squad_id to BaseSquad instance
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Squad config file not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        squads_cfg = data.get("squads")
        if not squads_cfg:
            raise ValueError(f"No 'squads' section found in {path}")

        loaded_squads: Dict[str, BaseSquad] = {}

        build = self._build_options(config, agent_kwargs)
        for squad_id, cfg in squads_cfg.items():
            loaded_squads[squad_id] = self._build_squad(squad_id, cfg, build)

        return loaded_squads

    def load_one(self, path: str | Path, squad_id: str, config: Optional[Dict[str, Any]] = None,
                 agent_kwargs: Optional[Dict[str, Any]] = None) -> BaseSquad:
        """
        Load a single squad by ID from a YAML file (only that squad's agents are built).
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Squad config file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            squads_cfg = (yaml.safe_load(f) or {}).get("squads") or {}
        if squad_id not in squads_cfg:
            available = ", ".join(sorted(squads_cfg.keys())) or "none"
            raise KeyError(
                f"Squad '{squad_id}' not found in config. Available squads: {available}"
            )
        return self._build_squad(squad_id, squads_cfg[squad_id], self._build_options(config, agent_kwargs))

    def _build_options(self, config, agent_kwargs) -> Dict[str, Any]:
        return {"config": self.config if config is None else config,
                "agent_kwargs": {**self.agent_kwargs, **(agent_kwargs or {})}}

    def _build_squad(self, squad_id: str, cfg: Dict[str, Any],
                     build: Optional[Dict[str, Any]] = None) -> BaseSquad:
        """
        Build a BaseSquad instance from one squad config block.
        """
        if not isinstance(cfg, dict):
            raise ValueError(f"Squad '{squad_id}' configuration must be a mapping/dictionary.")

        agent_names = cfg.get("agents", [])
        if not agent_names:
            raise ValueError(f"Squad '{squad_id}' must define at least one agent")

        build = build or self._build_options(None, None)
        agents = [self._create_agent(agent_name, squad_id, build) for agent_name in agent_names]
        monitor = self.monitor_cls() if self.monitor_cls else None

        squad = self.squad_cls(
            squad_id=squad_id,
            agents=agents,
            monitor=monitor,
        )

        squad.config = build["config"]
        squad.description = cfg.get("description", "")
        squad.flow = cfg.get("flow", [])
        squad.metadata = cfg

        # Squad coordinator (1.16): a solution may name its own synthesizer agent;
        # otherwise BaseSquad creates K9ContextSynthesizerAgent on first use.
        synthesis = synthesis_config(cfg)
        if synthesis["mode"] != "off" and synthesis.get("agent"):
            squad.synthesizer = self._create_agent(synthesis["agent"], squad_id, build)

        return squad

    def _create_agent(self, agent_name: str, squad_id: str, build: Optional[Dict[str, Any]] = None):
        """
        Create an agent instance: through the ``agent_loader`` (class from the
        agent YAML, config merged per agent), else through the registry.

        Registry supports:
          - registry.create(name)
          - registry.get(name) -> class
        """
        build = build or self._build_options(None, None)
        try:
            if self.agent_loader is not None:
                agent_cls = self.agent_loader.resolve_class(agent_name)
                return agent_cls(config=self.agent_loader.merge_with_global(agent_name, build["config"]),
                                 **build["agent_kwargs"])

            if hasattr(self.agent_registry, "create"):
                return self.agent_registry.create(agent_name)

            if hasattr(self.agent_registry, "get"):
                agent_cls = self.agent_registry.get(agent_name)
                return agent_cls()

            raise TypeError(
                "Agent registry must implement either 'create(name)' "
                "or 'get(name) -> class'"
            )

        except Exception as e:
            raise ValueError(
                f"Failed to create agent '{agent_name}' for squad '{squad_id}': {e}"
            ) from e