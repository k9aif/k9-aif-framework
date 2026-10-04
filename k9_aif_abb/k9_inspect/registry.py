# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""InspectionRuleRegistry — the rules an inspection runs.

Built-in rules are registered on first use; a solution or organisation adds its
own with InspectionRuleRegistry.register(MyRule) (Open/Closed: no edit here).
"""

from __future__ import annotations

from typing import Dict, List, Type

from .base_inspection_rule import BaseInspectionRule


class InspectionRuleRegistry:
    _rules: Dict[str, Type[BaseInspectionRule]] = {}
    _builtins_loaded = False

    @classmethod
    def register(cls, rule: Type[BaseInspectionRule]) -> Type[BaseInspectionRule]:
        if not rule.rule_id:
            raise ValueError(f"{rule.__name__} has no rule_id")
        cls._rules[rule.rule_id] = rule
        return rule

    @classmethod
    def unregister(cls, rule_id: str) -> None:
        cls._rules.pop(rule_id, None)

    @classmethod
    def all(cls) -> List[Type[BaseInspectionRule]]:
        if not cls._builtins_loaded:
            from . import rules  # noqa: F401  (registers the built-in rules)
            cls._builtins_loaded = True
        return [cls._rules[k] for k in sorted(cls._rules)]
