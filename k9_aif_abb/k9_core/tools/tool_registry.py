# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
ToolRegistry: what the framework knows about each tool before it runs.

Read once from ``security.tool_gate.tools`` and frozen: nothing can change an
entry while the process runs, and an agent never receives the registry.

    security:
      tool_gate:
        tools:
          release_payment:
            irreversible: true            # the default for any tool, declared or not
            verify:                       # argument -> the record it must match
              account: {entity: vendor, id_from: vendor, field: bank_account}
            connector:                    # where the tool lives, to run it after approval
              client: streamable_http
              params: {config: {kwargs: {url: "${PAYMENTS_MCP_URL}"}}}
            queue: payments-review
          lookup_invoice:
            irreversible: false

A tool that is not declared is treated as irreversible (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class RecordCheck:
    """One argument that must equal a field of a record looked up through k9x Origin."""
    argument: str
    entity: str
    id_from: str          # the argument holding the record's id
    field: str            # the field of the record the argument must equal


@dataclass(frozen=True)
class ToolSpec:
    name: str
    irreversible: bool = True
    verify: Tuple[RecordCheck, ...] = ()
    connector: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    queue: Optional[str] = None
    declared: bool = False
    require_assurance: Tuple[str, ...] = ()

    @classmethod
    def from_config(cls, name: str, raw: Dict[str, Any]) -> "ToolSpec":
        raw = raw or {}
        checks = []
        for argument, rule in (raw.get("verify") or {}).items():
            missing = [k for k in ("entity", "id_from", "field") if not (rule or {}).get(k)]
            if missing:
                raise ValueError(f"tool_gate.tools.{name}.verify.{argument}: missing {missing}")
            checks.append(RecordCheck(argument, rule["entity"], rule["id_from"], rule["field"]))
        irreversible = raw.get("irreversible", True)
        if not isinstance(irreversible, bool):
            raise ValueError(f"tool_gate.tools.{name}.irreversible must be true or false")
        return cls(
            name=name,
            irreversible=irreversible,
            verify=tuple(checks),
            connector=MappingProxyType(dict(raw.get("connector") or {})),
            queue=raw.get("queue"),
            declared=True,
            require_assurance=tuple(raw.get("require_assurance") or ()),
        )


class ToolRegistry:
    """Frozen map of tool name -> ToolSpec. Unknown tools are irreversible."""

    def __init__(self, specs: Optional[Dict[str, ToolSpec]] = None):
        self._specs: Mapping[str, ToolSpec] = MappingProxyType(dict(specs or {}))

    @classmethod
    def from_config(cls, tools: Optional[Dict[str, Any]]) -> "ToolRegistry":
        return cls({name: ToolSpec.from_config(name, raw) for name, raw in (tools or {}).items()})

    def lookup(self, tool_name: str) -> ToolSpec:
        spec = self._specs.get(tool_name)
        return spec if spec is not None else ToolSpec(name=tool_name, irreversible=True, declared=False)

    def __contains__(self, tool_name: str) -> bool:
        return tool_name in self._specs

    def names(self):
        return tuple(self._specs)
