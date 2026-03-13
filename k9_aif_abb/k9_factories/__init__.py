# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Patent Pending
# File: k9_aif_abb/k9_factories/__init__.py

from k9_aif_abb.k9_factories.message_factory import MessageFactory
from k9_aif_abb.k9_factories.monitor_factory import MonitorFactory
from k9_aif_abb.k9_factories.agent_factory import AgentFactory
# (import other factories as needed)

_factories = {}
_message_bus = None
_monitor = None


def bootstrap_all(config):
    """
    Initialize core ABB factories and global services (Monitor, MessageBus).
    Called once at framework startup.
    """
    global _factories, _message_bus, _monitor

    # 1. Create Monitor (local console or web console)
    _monitor = MonitorFactory.create(config)

    # 2. Create Message Bus (Redpanda / Kafka / LocalQueue)
    _message_bus = MessageFactory.create(config)

    # 3. Register all active factories (extend as needed)
    _factories = {
        "monitor": _monitor,
        "message_bus": _message_bus,
        "agent": AgentFactory,
        # add others like connector, llm, persistence, etc.
    }

    print("[OK] K9-AIF factories initialized.")
    print(f"[INFO] Message bus backend: {config['messaging'].get('backend')}")
    return _factories


def get_factory(name):
    """Fetch a registered factory instance."""
    return _factories.get(name)


def get_monitor():
    return _monitor


def get_message_bus():
    return _message_bus