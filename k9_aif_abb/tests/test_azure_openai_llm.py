# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# Tests: AzureOpenAILLM.generate() -- invocation, response parsing,
# timeout, 429, malformed output. Fake client (AsyncMock), no real Azure
# endpoint required -- same reasoning as every other provider test in
# this suite (OllamaLLM/OpenAILLM's own tests never hit a real backend).

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from k9_aif_abb.k9_core.inference.azure_openai_llm import AzureOpenAILLM


def _fake_response(content: str):
    """Mimics the openai SDK's ChatCompletion response shape closely
    enough for AzureOpenAILLM.generate()'s own access pattern
    (response.choices[0].message.content)."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _make_llm(fake_client):
    with patch("openai.AsyncAzureOpenAI", return_value=fake_client):
        return AzureOpenAILLM(
            api_key="test-key",
            azure_endpoint="https://my-resource.openai.azure.com",
            deployment="gpt-4o",
            api_version="2024-10-21",
        )


class TestAzureOpenAILLMInvocation:

    @pytest.mark.asyncio
    async def test_generate_returns_response_text(self):
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=_fake_response("The claim is approved."))
        )))
        llm = _make_llm(fake_client)

        result = await llm.generate("Should this claim be approved?")

        assert result == "The claim is approved."
        fake_client.chat.completions.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deployment_used_as_model_argument(self):
        """Azure routes by deployment name, passed as model= per-call --
        not baked into the client at construction time."""
        create_mock = AsyncMock(return_value=_fake_response("ok"))
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))
        llm = _make_llm(fake_client)

        await llm.generate("hello")

        _, kwargs = create_mock.call_args
        assert kwargs["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_system_prompt_none_accepted(self):
        """generate() must accept system_prompt=None -- K9ModelRouter
        always passes it as a kwarg, per CLAUDE.md's own documented
        gotcha for every LLM adapter."""
        create_mock = AsyncMock(return_value=_fake_response("ok"))
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))
        llm = _make_llm(fake_client)

        result = await llm.generate("hello", system_prompt=None)

        assert result == "ok"
        _, kwargs = create_mock.call_args
        roles = [m["role"] for m in kwargs["messages"]]
        assert "system" not in roles  # no system message sent when None

    @pytest.mark.asyncio
    async def test_system_prompt_included_when_given(self):
        create_mock = AsyncMock(return_value=_fake_response("ok"))
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))
        llm = _make_llm(fake_client)

        await llm.generate("hello", system_prompt="You are a claims reviewer.")

        _, kwargs = create_mock.call_args
        assert kwargs["messages"][0] == {"role": "system", "content": "You are a claims reviewer."}
        assert kwargs["messages"][1] == {"role": "user", "content": "hello"}


class TestAzureOpenAILLMFailureModes:

    @pytest.mark.asyncio
    async def test_timeout_returns_warn_string_not_raise(self):
        create_mock = AsyncMock(side_effect=TimeoutError("Request timed out"))
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))
        llm = _make_llm(fake_client)

        result = await llm.generate("hello")

        # Same convention as OllamaLLM/OpenAILLM -- [WARN]-prefixed
        # string, not a raised exception. llm_invoke() is what turns
        # this into a RuntimeError, one layer up.
        assert result.startswith("[WARN]")
        assert "timed out" in result.lower() or "timeout" in result.lower()

    @pytest.mark.asyncio
    async def test_rate_limit_429_returns_warn_string_not_raise(self):
        create_mock = AsyncMock(side_effect=Exception("Rate limit exceeded (429)"))
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))
        llm = _make_llm(fake_client)

        result = await llm.generate("hello")

        assert result.startswith("[WARN]")
        assert "429" in result or "rate limit" in result.lower()

    @pytest.mark.asyncio
    async def test_malformed_empty_content_returns_no_response_warning(self):
        """A successful API call that comes back with no actual content
        (content=None) must not be returned as an empty string silently
        -- same fallback OpenAILLM already uses."""
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=_fake_response(None))
        )))
        llm = _make_llm(fake_client)

        result = await llm.generate("hello")

        assert result == "[WARN] No response from model."

    @pytest.mark.asyncio
    async def test_malformed_whitespace_only_content_returns_no_response_warning(self):
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=_fake_response("   \n  "))
        )))
        llm = _make_llm(fake_client)

        result = await llm.generate("hello")

        assert result == "[WARN] No response from model."
