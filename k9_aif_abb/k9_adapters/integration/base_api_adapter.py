# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseApiAdapter — ABB for REST/SOAP/GraphQL API connectors.

Concrete SBBs implement call_endpoint(); execute() is the fixed template.
Config keys: url, method (default POST), headers, timeout (default 30), and the outbound guard (1.18.5,
``outbound_guard.py``): ``allowed_hosts`` (when set, the only destinations), ``allow_private_networks``
(let an agent-chosen URL reach internal addresses; default false). A URL taken from the payload (no ``url``
configured) is checked here; adapters that fill a configured URL check the final URL in call_endpoint().
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, Optional

from .base_integration_adapter import BaseIntegrationAdapter
from .outbound_guard import OutboundRefused, check_destination, host_is_templated


class BaseApiAdapter(BaseIntegrationAdapter):
    """ABB for deterministic HTTP/API calls — no LLM inference."""

    @abstractmethod
    def call_endpoint(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
    ) -> Any:
        """Execute the HTTP call. Return raw response (SA decides the shape)."""

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_input(payload)
        configured = self.config.get("url")
        url     = configured or payload.get("url", "")
        method  = self.config.get("method", "POST").upper()
        headers = {**self.config.get("headers", {}), **payload.get("headers", {})}
        if not configured:
            # The agent chose this URL: it may not reach internal or metadata addresses unless the
            # architect allowed it (allowed_hosts / allow_private_networks).
            check_destination(url, allowed_hosts=self.config.get("allowed_hosts"),
                              private_ok=bool(self.config.get("allow_private_networks")))
        try:
            result = self.call_endpoint(url, method, headers, payload)
            return {"adapter": self.adapter_name, "status": "success", "result": result}
        except OutboundRefused:
            raise                       # a security refusal is a block signal, never an error result
        except Exception as exc:
            return self.handle_error(exc, payload)

    def destination_private_ok(self, template: str) -> bool:
        """Internal addresses are fine when the architect wrote the host into the configured URL (not
        filled from the payload) or allowed them explicitly."""
        return bool(self.config.get("allow_private_networks")) or (
            bool(self.config.get("url")) and not host_is_templated(template))
