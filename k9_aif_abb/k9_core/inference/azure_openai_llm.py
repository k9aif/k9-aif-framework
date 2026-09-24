# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/inference/azure_openai_llm.py

import logging
from typing import Any, Optional
from k9_aif_abb.k9_core.inference.base_llm import BaseLLM


class AzureOpenAILLM(BaseLLM):
    """
    K9-AIF Inference SBB - AzureOpenAILLM
    ----------------------------------------
    Azure OpenAI Service backend (`azure.ai.openai` REST surface, via the
    `openai` package's AsyncAzureOpenAI client -- same SDK as OpenAILLM,
    different client construction and routing).

    Motivated by real evidence, not speculative provider coverage: a live
    IBM Process Studio blueprint (Account Maintenance Portfolio Management)
    resolved its tech stack to "Azure OpenAI GPT-4o (all AI agents), Azure
    tenant" -- Azure OpenAI is a real, common resolution for enterprise
    (especially IBM/Process-Studio-sourced) blueprints, not a hypothetical
    provider to support someday.

    Azure routes by *deployment name*, not raw model id -- an enterprise's
    deployment is frequently named differently from the underlying model
    (e.g. "prod-gpt4o-eastus2" serving gpt-4o). `deployment` is passed as
    the `model=` argument on each request rather than baked into the
    client at construction time (`azure_deployment=`), the more portable
    of the two supported patterns -- one client, callable against any
    deployment the credential has access to.

    Drop-in replacement for OllamaLLM/OpenAILLM -- same generate()
    contract. Provider is selected via backend: azure-openai in
    config.yaml (see AzureOpenAIProviderAdapter).
    """

    layer = "Inference SBB"

    def __init__(
        self,
        api_key: str,
        azure_endpoint: str,
        deployment: str,
        api_version: str = "2024-10-21",
        temperature: float = 0.3,
        max_tokens: int = 2048,
        monitor: Optional[Any] = None,
        **kwargs: Any,
    ):
        super().__init__(name="AzureOpenAILLM", monitor=monitor)
        self.deployment = deployment
        self.temperature = temperature
        self.max_tokens = max_tokens

        try:
            from openai import AsyncAzureOpenAI
        except ImportError as exc:
            raise ImportError(
                "openai package is required for AzureOpenAILLM. "
                "Run: pip install openai>=1.0"
            ) from exc

        self._client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
        )
        self.logger = logging.getLogger("AzureOpenAILLM")

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        await self.log(
            f"Sending inference request to Azure OpenAI (deployment={self.deployment})",
            "DEBUG",
        )
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        try:
            response = await self._client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            text = response.choices[0].message.content or ""
            text = text.strip()
            await self.log(f"Azure OpenAI responded ({len(text)} chars)", "INFO")
            return text or "[WARN] No response from model."
        except Exception as e:
            msg = f"Azure OpenAI request failed: {e}"
            await self.log(msg, "ERROR")
            return f"[WARN] Azure OpenAI call failed: {e}"
