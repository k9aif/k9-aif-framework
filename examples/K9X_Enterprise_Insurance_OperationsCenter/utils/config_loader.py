# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — utils/config_loader.py (SBB)

from __future__ import annotations

from typing import Any, Dict
import os
import yaml
import logging


log = logging.getLogger(__name__)


class ConfigLoaderError(Exception):
    """Raised when configuration loading fails."""


def load_yaml_file(path: str) -> Dict[str, Any]:
    """
    Load a single YAML file and return its contents as a dict.

    Args:
        path: Absolute or relative path to the YAML file.

    Returns:
        Parsed YAML as a dict.

    Raises:
        ConfigLoaderError: If the file is missing or malformed.
    """
    if not os.path.exists(path):
        raise ConfigLoaderError(f"Config file not found: {path}")

    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
            log.info("Loaded YAML: %s", path)
            return data
    except Exception as exc:
        raise ConfigLoaderError(f"Failed to load YAML {path}: {exc}") from exc


def load_yaml_dir(directory: str) -> Dict[str, Dict[str, Any]]:
    """
    Load all ``.yaml`` files in a directory and return a keyed dict.

    Each file must contain a ``name`` key that becomes the dict key.

    Args:
        directory: Path to a directory containing YAML files.

    Returns:
        Dict keyed by the ``name`` field in each YAML, e.g.::

            {
                "ClaimsTriageAgent": {...},
                "AuditAgent": {...},
                ...
            }

    Raises:
        ConfigLoaderError: If the directory is missing or any file lacks ``name``.
    """
    if not os.path.isdir(directory):
        raise ConfigLoaderError(f"Directory not found: {directory}")

    configs: Dict[str, Dict[str, Any]] = {}

    for file_name in sorted(os.listdir(directory)):
        if not file_name.endswith(".yaml"):
            continue

        path = os.path.join(directory, file_name)
        data = load_yaml_file(path)

        name = data.get("name")
        if not name:
            raise ConfigLoaderError(f"Missing 'name' in {file_name}")

        configs[name] = data

    log.info("Loaded %d configs from %s", len(configs), directory)
    return configs


def load_config_bundle(base_path: str) -> Dict[str, Any]:
    """
    Load the full EOC configuration bundle from the project layout.

    Expected structure under ``base_path``::

        agents/yaml/    ← per-agent YAML descriptors
        squads/yaml/    ← per-squad YAML descriptors
        config/         ← main config.yaml, squads.yaml, governance.yaml

    Args:
        base_path: Root path of the EOC project directory.

    Returns:
        Bundle dict::

            {
                "agents":    {"ClaimsTriageAgent": {...}, ...},
                "squads":    {"ClaimsProcessingSquad": {...}, ...},
                "config":    {...},   # from config/config.yaml
                "governance": {...},  # from config/governance.yaml
            }
    """
    agents_path = os.path.join(base_path, "agents", "yaml")
    squads_path = os.path.join(base_path, "squads", "yaml")
    config_path = os.path.join(base_path, "config", "config.yaml")
    governance_path = os.path.join(base_path, "config", "governance.yaml")

    bundle: Dict[str, Any] = {}

    bundle["agents"] = load_yaml_dir(agents_path) if os.path.isdir(agents_path) else {}
    bundle["squads"] = load_yaml_dir(squads_path) if os.path.isdir(squads_path) else {}
    bundle["config"] = load_yaml_file(config_path) if os.path.exists(config_path) else {}
    bundle["governance"] = load_yaml_file(governance_path) if os.path.exists(governance_path) else {}

    if not bundle["agents"]:
        log.warning("No agent YAML configs found in %s", agents_path)
    if not bundle["squads"]:
        log.warning("No squad YAML configs found in %s", squads_path)

    return bundle
