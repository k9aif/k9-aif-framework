# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_factories/filter_factory.py

"""
FilterFactory: static factory for K9X Filters (BaseFilter, 1.32.0).

Pre-registered (OOB, ``k9_aif_abb.k9_filters``):
    text_normalize     K9TextNormalizeFilter     in: NFKC, invisible characters, tag characters
    attention          K9AttentionFilter         in: quarantine, score, de-duplicate, prune, label
    structured_output  K9StructuredOutputFilter  out: JSON from the model's text, validated
    provenance         K9ProvenanceFilter        in + out: sources from k9x Origin answers

A solution adds its own by extending BaseFilter, then either names it in config::

    filters:
      chain:
        - {name: ticket_ids, class: TicketIdFilter, module: my_app.filters.ticket_ids, setting: 1}

or registers it at start-up and refers to it by name::

    FilterFactory.register("ticket_ids", TicketIdFilter)

Extra keys in a chain entry (``setting: 1`` above) are passed to the filter's ``from_config()``.
An unknown name, a module that can't be imported, or a class that isn't a BaseFilter raises.
"""

import importlib
import logging
from threading import Lock
from typing import Any, Dict, Type, Union

log = logging.getLogger("FilterFactory")

_OOB = {
    "text_normalize":    "k9_aif_abb.k9_filters.text_normalize:K9TextNormalizeFilter",
    "attention":         "k9_aif_abb.k9_filters.attention:K9AttentionFilter",
    "structured_output": "k9_aif_abb.k9_filters.structured_output:K9StructuredOutputFilter",
    "provenance":        "k9_aif_abb.k9_filters.provenance:K9ProvenanceFilter",
}


def _load(path: str):
    module, _, cls = path.partition(":")
    return getattr(importlib.import_module(module), cls)


class FilterFactory:
    """Static Factory: provisions BaseFilter implementations."""

    _registry: Dict[str, Union[str, Type[Any]]] = dict(_OOB)
    _lock = Lock()

    def __init__(self, *args, **kwargs):
        raise RuntimeError("FilterFactory is static and cannot be instantiated")

    @staticmethod
    def register(name: str, filter_cls: Type[Any]) -> None:
        from k9_aif_abb.k9_core.filters.base_filter import BaseFilter
        if not (isinstance(filter_cls, type) and issubclass(filter_cls, BaseFilter)):
            raise TypeError(f"FilterFactory.register({name!r}): {filter_cls!r} is not a BaseFilter subclass")
        with FilterFactory._lock:
            FilterFactory._registry[name] = filter_cls

    @staticmethod
    def available() -> list:
        return sorted(FilterFactory._registry)

    @staticmethod
    def create(spec: Union[str, Dict[str, Any]]):
        """Build one filter from a chain entry: a name, or a mapping with ``name:`` and optionally
        ``class:`` + ``module:`` and the filter's own settings."""
        from k9_aif_abb.k9_core.filters.base_filter import BaseFilter

        settings: Dict[str, Any] = {}
        if isinstance(spec, str):
            name = spec
        elif isinstance(spec, dict) and spec.get("name"):
            name = str(spec["name"])
            settings = {k: v for k, v in spec.items() if k not in ("name", "class", "module")}
        else:
            raise ValueError(f"filters.chain entry {spec!r}: give a name, or a mapping with name:")

        if isinstance(spec, dict) and spec.get("class"):
            if not spec.get("module"):
                raise ValueError(f"filter {name}: class: needs module:")
            cls = getattr(importlib.import_module(spec["module"]), spec["class"])
        else:
            entry = FilterFactory._registry.get(name)
            if entry is None:
                raise ValueError(f"unknown filter {name!r}: known {FilterFactory.available()}; "
                                 "an SBB filter needs class: and module:, or FilterFactory.register()")
            cls = _load(entry) if isinstance(entry, str) else entry

        if not (isinstance(cls, type) and issubclass(cls, BaseFilter)):
            raise TypeError(f"filter {name}: {cls!r} is not a BaseFilter subclass")
        instance = cls.from_config(settings)
        if not instance.name:
            instance.name = name
        return instance
