# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — utils package

"""
EOC Utilities Package
=====================

Runtime support utilities for the K9X Enterprise Insurance Operations Center.

Modules
-------

config_loader
    YAML configuration loading helpers.

    - ``load_yaml_file(path)`` — load a single YAML file.
    - ``load_yaml_dir(directory)`` — load all YAML files in a directory, keyed by ``name``.
    - ``load_config_bundle(base_path)`` — load the full agent + squad + config bundle.

bootstrap
    EOCBootstrap class — single entry point for application startup.

    Registers all 8 agents and 7 orchestrators in the K9-AIF runtime
    registries, loads squads from YAML via SquadLoader, and instantiates
    the root EOCOrchestrator.

    Usage::

        from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.bootstrap import EOCBootstrap

        bootstrap = EOCBootstrap()
        bootstrap.initialize()
        orch = bootstrap.get_orchestrator("ClaimsProcessingOrchestrator")

systems_check
    Pre-flight system health checks: config structure, runtime directories,
    OCR tool availability, LLM reachability, messaging, storage, Neo4j.

    Usage::

        from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.systems_check import run_system_checks
        ok = run_system_checks(config)
"""
