# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Intent Router ABB
# Routes detected intents to orchestrators by merging ABB + SBB orchestrator registries.
# Publishes structured console events through the global message bus (Redpanda/WebSocket).

import yaml
import logging
import glob
from copy import deepcopy
from pathlib import Path
from typing import Dict, Any, Optional
from k9_aif_abb.k9_core.base_component import BaseComponent
# REMOVE or COMMENT OUT this line to break the circular import
# from k9_aif_abb.k9_factories.message_factory import MessageFactory


class IntentRouter(BaseComponent):
    """
    K9-AIF Intent Router ABB
    ------------------------
    Centralized routing controller that:
      - Loads orchestrators.yaml from ABB + SBB projects.
      - Merges all orchestrator registries into a single runtime table.
      - Publishes routing decisions as structured events (visible in console).
    """

    layer = "Routing ABB"

    # ----------------------------------------------------------------------
    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, message_bus=None):
        super().__init__(monitor=monitor, message_bus=message_bus)
        self.config = config or {}
        self.logger = logging.getLogger("IntentRouter")

        # Local import here to avoid circular dependency
        from k9_aif_abb.k9_factories.message_factory import MessageFactory
        self.messaging = message_bus or MessageFactory.create(self.config)

        self.registry = self.load_registry()