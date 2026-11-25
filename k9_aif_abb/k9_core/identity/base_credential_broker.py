# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseCredentialBroker: credentials for one outbound call, acting for the caller (1.36.0).

A connector configured with ``on_behalf_of: {audience: <client>}`` asks the
broker for the headers of one call. The broker returns credentials addressed
to that audience that name the caller (``sub``) and this application as the
party acting for them. The connector never forwards the caller's own token
(token passthrough is forbidden by the MCP authorization spec, and the
receiving server would rightly reject a token addressed to someone else).

Fail closed: no caller, no subject token, or a refused exchange raises
``CredentialUnavailableError`` (a ``PermissionError``), which propagates like a
Shield block. There is never a fall back to a shared key.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional

from k9_aif_abb.k9_core.identity.caller_context import CallerContext


class CredentialUnavailableError(PermissionError):
    """No credentials could be issued for this caller and audience; the call must not run."""


class BaseCredentialBroker(ABC):
    """ABB: turn the verified caller into request headers for one audience."""

    @abstractmethod
    def headers_for(self, audience: str, caller: CallerContext, *,
                    agent: Optional[str] = None, connector: Optional[str] = None) -> Dict[str, str]:
        """Headers (normally ``Authorization: Bearer ...``) for one call to ``audience``,
        acting for ``caller``. ``agent`` and ``connector`` are for the audit record.
        Raises ``CredentialUnavailableError`` when it can't issue them."""
        raise NotImplementedError
