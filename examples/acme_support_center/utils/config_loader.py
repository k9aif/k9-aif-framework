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
    Load a single YAML file.
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
    Load all YAML files in a directory.

    Returns:
        {
            "triage_agent": {...},
            "knowledge_agent": {...},
            ...
        }
    """
    if not os.path.isdir(directory):
        raise ConfigLoaderError(f"Directory not found: {directory}")

    configs: Dict[str, Dict[str, Any]] = {}

    for file_name in os.listdir(directory):
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
    Load full configuration bundle.

    Expected structure:
        base_path/
            agents/yaml/
            squads/yaml/
            config.yaml (optional)

    Returns:
        {
            "agents": {...},
            "squads": {...},
            "config": {...}
        }
    """
    agents_path = os.path.join(base_path, "agents", "yaml")
    squads_path = os.path.join(base_path, "squads", "yaml")
    config_path = os.path.join(base_path, "config.yaml")

    bundle: Dict[str, Any] = {}

    # Agents
    if os.path.isdir(agents_path):
        bundle["agents"] = load_yaml_dir(agents_path)
    else:
        log.warning("Agents directory not found: %s", agents_path)
        bundle["agents"] = {}

    # Squads
    if os.path.isdir(squads_path):
        bundle["squads"] = load_yaml_dir(squads_path)
    else:
        log.warning("Squads directory not found: %s", squads_path)
        bundle["squads"] = {}

    # Optional global config
    if os.path.exists(config_path):
        bundle["config"] = load_yaml_file(config_path)
    else:
        bundle["config"] = {}

    return bundle