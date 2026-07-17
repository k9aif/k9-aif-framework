# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/inference/watsonx_llm.py

import time
import traceback
from typing import Any, Optional

import aiohttp

from k9_aif_abb.k9_core.inference.base_llm import BaseLLM

_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
_DEFAULT_WATSONX_URL = "https://us-south.ml.cloud.ibm.com"
_API_VERSION = "2024-05-31"


class WatsonxLLM(BaseLLM):
    """
    K9-AIF Inference SBB - WatsonxLLM
    ----------------------------------
    IBM watsonx.ai text generation backend, called directly over its REST
    API (no ibm-watsonx-ai SDK dependency — one aiohttp call for the IAM
    token exchange, one for generation).

    watsonx.ai requires three things Ollama/OpenAI don't:
      - an IAM access token (exchanged from the API key, short-lived)
      - a project_id (or space_id) the model call is billed/scoped under
      - a region-specific base URL (default: us-south)

    Drop-in replacement for OllamaLLM/OpenAILLM — same generate() contract.
    Provider is selected via backend: watsonx in config.yaml.
    """

    layer = "Inference SBB"

    def __init__(
        self,
        api_key: str,
        project_id: str,
        model: str = "ibm/granite-13b-instruct-v2",
        base_url: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: int = 120,
        monitor: Optional[Any] = None,
        **kwargs: Any,
    ):
        super().__init__(name="WatsonxLLM", monitor=monitor)
        if not api_key:
            raise ValueError("WatsonxLLM requires an IBM Cloud API key")
        if not project_id:
            raise ValueError("WatsonxLLM requires a watsonx project_id")

        self.api_key = api_key
        self.project_id = project_id
        self.model = model
        self.base_url = (base_url or _DEFAULT_WATSONX_URL).rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = aiohttp.ClientTimeout(total=timeout)

        # IAM tokens are bearer tokens valid ~1hr — cache in the instance
        # (LLMFactory caches one WatsonxLLM per model alias) rather than
        # re-exchanging the API key on every single inference call.
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        if self._token and time.monotonic() < self._token_expiry:
            return self._token

        async with session.post(
            _IAM_TOKEN_URL,
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": self.api_key,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            body = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"IAM token exchange failed: HTTP {resp.status} {body}")

            self._token = body["access_token"]
            # Refresh a minute early rather than exactly on expiry.
            self._token_expiry = time.monotonic() + max(body.get("expires_in", 3600) - 60, 60)
            return self._token

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        await self.log(f"Sending inference request to watsonx.ai ({self.model})", "DEBUG")
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        url = f"{self.base_url}/ml/v1/text/generation?version={_API_VERSION}"
        payload = {
            "model_id": self.model,
            "input": full_prompt,
            "project_id": self.project_id,
            "parameters": {
                "decoding_method": "greedy",
                "max_new_tokens": self.max_tokens,
                "temperature": self.temperature,
            },
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                token = await self._get_token(session)
                async with session.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                ) as resp:
                    body = await resp.text()
                    if resp.status != 200:
                        msg = f"watsonx.ai HTTP {resp.status} | model={self.model} | body={body}"
                        await self.log(msg, "WARNING")
                        return f"[WARN] {msg}"

                    import json as _json
                    data = _json.loads(body)
                    results = data.get("results") or []
                    text = (results[0].get("generated_text", "") if results else "").strip()
                    await self.log(f"watsonx.ai responded ({len(text)} chars)", "INFO")
                    return text or "[WARN] No response from model."

        except Exception as e:
            msg = f"watsonx.ai request failed: {e}"
            await self.log(msg, "ERROR")
            traceback.print_exc()
            return f"[WARN] watsonx.ai connection failed: {e}"
