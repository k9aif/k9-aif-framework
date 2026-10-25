# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_factories/monitor_factory.py

from typing import Any, Dict, Type, List
from threading import Lock
import logging
from k9_aif_abb.k9_core.monitoring.monitor_server import MonitorServer


class MonitorFactory:
    """Static Factory - provisions Monitor backends and unified MonitorServer."""

    _registry: Dict[str, Type[Any]] = {}
    _bootstrapped = False
    _lock = Lock()
    logger = logging.getLogger("MonitorFactory")

    def __init__(self, *args, **kwargs):
        raise RuntimeError("MonitorFactory is static and cannot be instantiated")

    @staticmethod
    def register(name: str, monitor_cls: Type[Any]) -> None:
        with MonitorFactory._lock:
            MonitorFactory._registry[name] = monitor_cls
            MonitorFactory.logger.debug(f"Registered monitor backend '{name}'")

    @staticmethod
    def get(name: str, **kwargs: Any):
        try:
            cls = MonitorFactory._registry[name]
            return cls(**kwargs)
        except KeyError:
            raise ValueError(f"Unknown monitor backend: {name}")

    @staticmethod
    def bootstrap() -> None:
        if MonitorFactory._bootstrapped:
            return
        MonitorFactory._bootstrapped = True
        MonitorFactory.logger.info("[Factory] Bootstrapped MonitorFactory")

    @staticmethod
    def load_from_config(config: Dict[str, Any] = None) -> MonitorServer:
        """Build the MonitorServer from ``monitors`` / ``common_tags`` in *config*.

        With no ``monitors`` key, the framework's own config.yaml (found next to this package, not relative to
        the working directory) supplies the defaults. A monitor entry that can't be built raises.
        """
        cfg = config or {}
        if "monitors" not in cfg:
            import yaml
            from pathlib import Path
            default = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
            cfg = (yaml.safe_load(default.read_text(encoding="utf-8")) or {}) if default.is_file() else {}
        monitor_defs = cfg.get("monitors") or []
        common_tags = cfg.get("common_tags", {"app": "K9-AIF"})
        monitors: List[Any] = []
        for entry in monitor_defs:
            try:
                module_name, class_name = entry["class"].rsplit(".", 1)
                module = __import__(module_name, fromlist=[class_name])
                cls = getattr(module, class_name)
            except Exception as exc:
                raise ValueError(f"MonitorFactory: can't build monitor {entry!r}: {exc}") from exc
            MonitorFactory.register(entry["name"], cls)
            monitors.append(cls(**(entry.get("params") or entry.get("kwargs") or {})))   # both spellings are in use
        return MonitorServer(monitors=monitors, common_tags=common_tags)

    # ------------------------------------------------------------------
    # Entry point for bootstrap_all()
    # ------------------------------------------------------------------
    @staticmethod
    def create(config) -> MonitorServer:
        """The MonitorServer for this configuration.

        Before 1.19.0 this ignored *config*: it read "k9_aif_abb/config/config.yaml" relative to the working
        directory, which an installed package normally doesn't have, and the error was swallowed, so an
        application's monitors never applied and monitoring was silently empty.
        """
        return MonitorFactory.load_from_config(config)