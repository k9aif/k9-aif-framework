# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF - Async OllamaLLM (governed inference bridge)

import aiohttp
import json
import traceback
import asyncio
from typing import Any, Optional
from k9_aif_abb.k9_core.inference.base_llm import BaseLLM


class OllamaLLM(BaseLLM):
    """
    K9-AIF Inference SBB - Async OllamaLLM
    --------------------------------------
    - Asynchronous generation using aiohttp.
    - Fully compatible with ChatAgent (await self.llm.generate()).
    - Logs safely through BaseLLM.
    """

    layer = "Inference SBB"

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.1:latest",
        timeout: int = 120,
        monitor: Optional[Any] = None,
        **kwargs: Any,
    ):
        super().__init__(name="OllamaLLM", monitor=monitor)
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.kwargs = kwargs

    def _build_options(self) -> dict:
        """Translate K9-AIF's config keys (temperature, max_tokens, num_ctx)
        into Ollama's `options` object. Previously self.kwargs was stored
        here and never read again -- every app's configured temperature/
        max_tokens silently had zero effect and Ollama ran on its own raw
        defaults the whole time. Confirmed 2026-09-03 via a real DAS
        PackageBuilderAgent report that truncated mid-sentence despite a
        configured max_tokens: 4096."""
        options = {}
        temperature = self.kwargs.get("temperature")
        if temperature is not None:
            options["temperature"] = temperature
        max_tokens = self.kwargs.get("max_tokens")
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        num_ctx = self.kwargs.get("num_ctx")
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        return options

    # ----------------------------------------------------------
    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        await self.log(f"Sending inference request to Ollama ({self.model})", "DEBUG")
        url = f"{self.host}/api/generate"
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        if system_prompt:
            payload["system"] = system_prompt
        options = self._build_options()
        if options:
            payload["options"] = options
        # `think` is a top-level Ollama field, not part of `options`. Hybrid
        # reasoning models (Qwen3 family included) spend part of num_predict
        # on an invisible "thinking" field before the real "response" even
        # starts -- confirmed live: num_predict=15 against qwen3.8:27b spent
        # all 15 tokens on thinking and returned an EMPTY response with
        # done_reason="length". think: false skips that phase entirely, so
        # the full token budget goes to the actual answer.
        think = self.kwargs.get("think")
        if think is not None:
            payload["think"] = think

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, json=payload) as resp:
                    body = await resp.text()

                    if resp.status != 200:
                        msg = f"Ollama HTTP {resp.status} | model={self.model} | body={body}"
                        await self.log(msg, "WARNING")
                        return f"[WARN] {msg}"

                    data = await resp.json()
                    text = data.get("response", "").strip()
                    await self.log(f"Ollama responded ({len(text)} chars)", "INFO")
                    return text or "[WARN] No response from model."

        except Exception as e:
            msg = f"Ollama request failed: {e}"
            await self.log(msg, "ERROR")
            traceback.print_exc()
            return f"[WARN] Ollama connection failed: {e}"

    # ----------------------------------------------------------
    async def generate_stream(self, prompt: str, system_prompt: str = None):
        """
        Yield response text incrementally using Ollama's NDJSON streaming API
        (``stream: true``). Each line of the response body is a JSON object
        with a ``response`` fragment; the final line has ``done: true``.
        """
        await self.log(f"Streaming inference request to Ollama ({self.model})", "DEBUG")
        url = f"{self.host}/api/generate"
        payload = {"model": self.model, "prompt": prompt, "stream": True}
        if system_prompt:
            payload["system"] = system_prompt
        options = self._build_options()
        if options:
            payload["options"] = options
        think = self.kwargs.get("think")
        if think is not None:
            payload["think"] = think

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        msg = f"Ollama HTTP {resp.status} | model={self.model} | body={body}"
                        await self.log(msg, "WARNING")
                        yield f"[WARN] {msg}"
                        return

                    async for line in resp.content:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        chunk = data.get("response", "")
                        if chunk:
                            yield chunk
                        if data.get("done"):
                            break

            await self.log("Ollama stream complete", "INFO")

        except Exception as e:
            msg = f"Ollama streaming request failed: {e}"
            await self.log(msg, "ERROR")
            traceback.print_exc()
            yield f"[WARN] Ollama connection failed: {e}"

    # ----------------------------------------------------------
    async def start(self):
        """Initialize aiohttp session (optional)."""
        if not self.session:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        await self.log(f"OllamaLLM({self.model}) started", "INFO")

    async def stop(self):
        """Close aiohttp session (graceful shutdown)."""
        if self.session:
            await self.session.close()
            self.session = None
        await self.log(f"OllamaLLM({self.model}) stopped", "INFO")