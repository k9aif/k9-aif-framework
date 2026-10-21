# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Outbound guard (1.18.5): where an API adapter may send a request.

An agent's payload reaches the network through API adapters: it fills the placeholders of a configured URL
(``https://erp/api/invoices/{id}``), or, when no URL is configured, it supplies the URL itself. Without a
guard an agent (or text injected into it) can steer that request anywhere: to a cloud metadata endpoint
(``169.254.169.254``, which hands out credentials), to an internal admin service, or to another host by
smuggling ``../``, ``@`` or ``?`` into a placeholder. This module is the one place those rules live:

* placeholder values are URL-encoded, so a value can never change the host, path structure or query;
* link-local, metadata, unspecified and multicast addresses are always refused (no legitimate API lives there);
* private and loopback addresses are allowed only where the architect chose them: the host is written in the
  configured URL (not filled from the payload), listed in ``allowed_hosts``, or ``allow_private_networks`` is
  set. An agent-chosen URL never reaches the internal network by default;
* ``allowed_hosts``, when set, is the complete list of destinations (exact host or ``*.example.com``);
* every redirect hop is checked again (``follow`` in HttpApiAdapter).

A refusal raises ``OutboundRefused`` (a ``PermissionError``, the framework's block signal); the adapter does
not turn it into an error result.

Limits: addresses are checked when resolved here; a DNS answer that changes between this check and the
connection (rebinding) is not caught. Network policy (egress firewalls, security groups) remains the outer
control; this is the inner one, inside the code an agent can reach.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, urlsplit

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Never a legitimate API destination: link-local (incl. the AWS/GCP/Azure metadata address 169.254.169.254),
# AWS's IPv6 metadata address, Alibaba Cloud's metadata address, unspecified and multicast addresses.
_ALWAYS_BLOCKED = [ipaddress.ip_network(n) for n in (
    "169.254.0.0/16", "fe80::/10", "fd00:ec2::254/128", "100.100.100.200/32",
    "0.0.0.0/8", "::/128", "224.0.0.0/4", "ff00::/8")]


class OutboundRefused(PermissionError):
    """An outbound request the guard will not send."""


def fill_url(template: str, fields: Dict[str, Any]) -> str:
    """Fill ``{name}`` placeholders from the payload, each value URL-encoded (``/``, ``?``, ``#``, ``@`` and
    ``..`` become literal text, never URL structure). A placeholder with no scalar value is left as written."""
    def sub(m: "re.Match[str]") -> str:
        v = fields.get(m.group(1))
        if isinstance(v, (str, int, float)) and not isinstance(v, bool):
            return quote(str(v), safe="")
        return m.group(0)
    return _PLACEHOLDER.sub(sub, template or "")


def host_is_templated(template: str) -> bool:
    """True when the host part of a configured URL is filled from the payload (the agent picks the host)."""
    return "{" in urlsplit(template or "").netloc


def _host_allowed(host: str, allowed_hosts: Iterable[str]) -> bool:
    host = host.lower().rstrip(".")
    for pat in allowed_hosts:
        pat = str(pat).lower().strip().rstrip(".")
        if pat.startswith("*.") and (host.endswith(pat[1:]) or host == pat[2:]):
            return True
        if host == pat:
            return True
    return False


def _addresses(host: str) -> List[ipaddress._BaseAddress]:
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []                      # unresolvable: the request itself will fail; nothing to send to
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0].split("%")[0]))
        except ValueError:
            continue
    return out


def check_destination(url: str, *, allowed_hosts: Optional[Iterable[str]] = None,
                      private_ok: bool = False) -> None:
    """Raise OutboundRefused unless ``url`` may be requested. ``private_ok``: the architect chose this host
    (configured URL, listed host, or allow_private_networks)."""
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise OutboundRefused(f"outbound request refused: not an http(s) URL ({url!r})")
    host = parts.hostname
    allowed = list(allowed_hosts or [])
    if allowed and not _host_allowed(host, allowed):
        raise OutboundRefused(f"outbound request refused: {host} is not in allowed_hosts")
    for addr in _addresses(host):
        if any(addr in net for net in _ALWAYS_BLOCKED):
            raise OutboundRefused(f"outbound request refused: {host} resolves to {addr} (link-local / metadata "
                                  f"/ unspecified / multicast addresses are never API destinations)")
        if (addr.is_private or addr.is_loopback or addr.is_reserved) and not (private_ok or allowed):
            raise OutboundRefused(f"outbound request refused: {host} resolves to the internal address {addr}; "
                                  f"an agent-chosen URL may reach internal hosts only if they are listed in "
                                  f"allowed_hosts (or allow_private_networks is set)")
