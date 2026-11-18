# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""K9ModelProvider closes the OpenAI clients it opened on the run's own event loop, whether the run ends or fails."""

import asyncio

import pytest

pytest.importorskip("agents")

from agents import RunConfig  # noqa: E402

from k9_aif_abb.k9_adapters.openai_agents.k9_model_provider import K9ModelProvider, run_closing_provider  # noqa: E402


class _Client:
    closed = False

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("fails", [False, True])
def test_clients_closed_after_run(fails):
    provider = K9ModelProvider({})
    client = _Client()
    provider._clients.append(client)

    async def run():
        if fails:
            raise RuntimeError("model down")
        return "ok"

    coro = run_closing_provider(RunConfig(model_provider=provider), run)
    if fails:
        with pytest.raises(RuntimeError):
            asyncio.run(coro)
    else:
        assert asyncio.run(coro) == "ok"
    assert client.closed and provider._clients == []
