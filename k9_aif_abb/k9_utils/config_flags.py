# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""On/off settings read from configuration.

A setting such as ``security.shield.enabled`` or ``governance.guardian.enabled``
is often driven from ``.env`` (``enabled: "${K9_GUARDIAN_ENABLED:-true}"``). After
``load_yaml`` expands it, the value is the *string* ``"true"``, not the boolean
``True``; a check written as ``value is True`` then treats it as off, and a plain
``if value`` treats the string ``"false"`` as on. ``config_flag`` reads all of
these the same way, for the framework at run time and for ``k9_inspect`` reading
the raw YAML (where an unexpanded ``${VAR:-default}`` is judged by its default).
"""

from __future__ import annotations

import re
from typing import Any, Optional

_TRUE = {"true", "1", "yes", "on", "y"}
_FALSE = {"false", "0", "no", "off", "n", ""}
_PLACEHOLDER = re.compile(r"\$\{[^}:]+(?::-([^}]*))?\}")


def config_flag(value: Any, default: Optional[bool] = None) -> Optional[bool]:
    """True / False for a configuration on/off value; ``default`` if it is unset
    or not recognisable as either."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip()
    placeholder = _PLACEHOLDER.fullmatch(text)
    if placeholder:                      # unexpanded ${VAR:-default}: judge the default
        if placeholder.group(1) is None:
            return default
        text = placeholder.group(1).strip()
    text = text.lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return default
