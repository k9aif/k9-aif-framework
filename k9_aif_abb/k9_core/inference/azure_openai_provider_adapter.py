# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/inference/azure_openai_provider_adapter.py

import os
from typing import Any, Dict

from k9_aif_abb.k9_core.inference.base_provider_adapter import BaseProviderAdapter
from k9_aif_abb.k9_core.inference.base_llm import BaseLLM


class AzureOpenAIProviderAdapter(BaseProviderAdapter):
    """
    K9-AIF Inference SBB — AzureOpenAIProviderAdapter
    ----------------------------------------------------
    Creates an AzureOpenAILLM. Azure OpenAI has a genuinely different
    resolution shape from plain OpenAI-compatible endpoints (endpoint +
    api-version + deployment name, not a single base_url + model id) --
    a sibling adapter, not an OpenAIProviderAdapter subclass, same
    relationship OpenAIProviderAdapter and WatsonxProviderAdapter already
    have to each other.

    Required config.yaml keys (inference.llm_factory):
        azure_endpoint:  https://<resource>.openai.azure.com  (or
                          AZURE_OPENAI_ENDPOINT env var / ${VAR} placeholder)
        api_version:     e.g. "2024-10-21" (sensible default provided)
        api_key_env:     name of the .env variable holding the key
                          (preferred over a raw/legacy api_key value --
                          same resolution order as OpenAIProviderAdapter)

    deployment resolution: extra_kwargs["deployment"] or
    factory_cfg["deployment"], falling back to model_name if neither is
    set -- most enterprises name their deployment after the underlying
    model (e.g. "gpt-4o"), but Azure allows an arbitrary deployment name
    per environment (e.g. "prod-gpt4o-eastus2"), so an explicit override
    is supported, not assumed away.

    API keys must NEVER be stored as raw values in config.yaml.
    """

    @property
    def provider_name(self) -> str:
        return "azure-openai"

    def create_llm(
        self,
        model_name: str,
        factory_cfg: Dict[str, Any],
        extra_kwargs: Dict[str, Any],
    ) -> BaseLLM:
        from k9_aif_abb.k9_core.inference.azure_openai_llm import AzureOpenAILLM

        api_key = self._resolve_api_key(factory_cfg)
        azure_endpoint = self._resolve_endpoint(factory_cfg)
        api_version = factory_cfg.get("api_version", "").strip() or "2024-10-21"

        extra_kwargs = dict(extra_kwargs)  # don't mutate the caller's dict
        deployment = (
            extra_kwargs.pop("deployment", None)
            or factory_cfg.get("deployment", "").strip()
            or model_name
        )

        return AzureOpenAILLM(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            deployment=deployment,
            api_version=api_version,
            **extra_kwargs,
        )

    # ── private helpers ────────────────────────────────────────────────

    def _resolve_api_key(self, factory_cfg: Dict[str, Any]) -> str:
        # 1. Explicit env var name in config (preferred) -- same
        #    resolution order as OpenAIProviderAdapter, for consistency.
        env_var = factory_cfg.get("api_key_env", "").strip()
        if env_var:
            value = os.environ.get(env_var, "")
            if not value:
                raise EnvironmentError(
                    f"Environment variable '{env_var}' (api_key_env) is not set. "
                    f"Add it to your .env file before running."
                )
            return value

        # 2. api_key with ${VAR} placeholder (legacy / convenience)
        raw_key = factory_cfg.get("api_key", "").strip()
        if raw_key:
            resolved = os.path.expandvars(raw_key)
            if resolved and not resolved.startswith("$"):
                return resolved

        # 3. Implicit AZURE_OPENAI_API_KEY fallback
        fallback = os.environ.get("AZURE_OPENAI_API_KEY", "")
        if fallback:
            return fallback

        raise EnvironmentError(
            "Azure OpenAI backend requires an API key. "
            "Set api_key_env: AZURE_OPENAI_API_KEY in config.yaml "
            "and export the variable in your .env file."
        )

    def _resolve_endpoint(self, factory_cfg: Dict[str, Any]) -> str:
        raw = factory_cfg.get("azure_endpoint", "").strip()
        resolved = os.path.expandvars(raw) if raw else ""
        if resolved and not resolved.startswith("$"):
            return resolved

        fallback = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        if fallback:
            return fallback

        raise EnvironmentError(
            "Azure OpenAI backend requires azure_endpoint. "
            "Set it in config.yaml (inference.llm_factory.azure_endpoint), "
            "e.g. https://<resource>.openai.azure.com, or export "
            "AZURE_OPENAI_ENDPOINT."
        )
