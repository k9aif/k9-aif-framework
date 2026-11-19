# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Property: the framework has one sync-over-async bridge (k9_utils/async_bridge.py, 1.31.0).

Private copies drift: one of the eight copies that existed before 1.31.0 masked a coroutine's
own RuntimeError. Test: no framework module outside the bridge calls asyncio.run(), except the
sync entry points that refuse inside a running loop on purpose and offer an async twin.
"""

import re
from pathlib import Path

ABB = Path(__file__).resolve().parent.parent
ALLOWED = {
    "k9_utils/async_bridge.py",
    # execute_flow() refuses inside a running loop and points to execute_flow_async().
    "k9_adapters/openai_agents/openai_agents_orchestrator_adapter.py",
    "k9_adapters/claude_agent_sdk/claude_agent_sdk_orchestrator_adapter.py",
}
CALL = re.compile(r"\basyncio\.run\(")


def test_no_private_sync_over_async_bridge():
    offenders = []
    for p in ABB.rglob("*.py"):
        rel = p.relative_to(ABB).as_posix()
        if rel.startswith("tests/") or rel in ALLOWED:
            continue
        text = p.read_text(errors="ignore")
        code = re.sub(r'"""[\s\S]*?"""', "", text)       # docstrings and comments may mention it
        code = re.sub(r"#.*$", "", code, flags=re.M)
        if CALL.search(code):
            offenders.append(rel)
    assert not offenders, f"use k9_aif_abb.k9_utils.async_bridge.run_sync instead of asyncio.run in: {offenders}"
