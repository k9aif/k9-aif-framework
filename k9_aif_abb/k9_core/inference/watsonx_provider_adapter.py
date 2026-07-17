# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/inference/watsonx_provider_adapter.py

import os
from typing import Any, Dict

from k9_aif_abb.k9_core.inference.base_provider_adapter import BaseProviderAdapter
from k9_aif_abb.k9_core.inference.base_llm import BaseLLM


class WatsonxProviderAdapter(BaseProviderAdapter):
    """
    K9-AIF Inference SBB — WatsonxProviderAdapter
    -----------------------------------------------
    Creates a WatsonxLLM from the factory config.

    Config keys read from inference.llm_factory:
        base_url          — watsonx.ai region URL (default: us-south)
        project_id        — required; watsonx project to bill/scope under
        project_id_env    — env var name holding project_id (preferred over
                             a literal project_id in config — project IDs are
                             not secrets but keeping them env-driven matches
                             the rest of the adapter pattern and avoids
                             hardcoding a customer's project into config.yaml)
        api_key_env       — env var name holding the IBM Cloud API key

    API key resolution order (same convention as OpenAIProviderAdapter):
        1. api_key_env: ENV_VAR_NAME  — preferred
        2. Environment variable WATSONX_API_KEY — fallback
    API keys must NEVER be stored as raw values in config.yaml.
    """

    @property
    def provider_name(self) -> str:
        return "watsonx"

    def create_llm(
        self,
        model_name: str,
        factory_cfg: Dict[str, Any],
        extra_kwargs: Dict[str, Any],
    ) -> BaseLLM:
        from k9_aif_abb.k9_core.inference.watsonx_llm import WatsonxLLM

        api_key    = self._resolve_api_key(factory_cfg)
        project_id = self._resolve_project_id(factory_cfg)
        base_url   = factory_cfg.get("base_url", "").strip() or None

        return WatsonxLLM(
            api_key=api_key,
            project_id=project_id,
            model=model_name,
            base_url=base_url,
            **extra_kwargs,
        )

    # ── private helpers ────────────────────────────────────────────────

    def _resolve_api_key(self, factory_cfg: Dict[str, Any]) -> str:
        env_var = factory_cfg.get("api_key_env", "").strip()
        if env_var:
            value = os.environ.get(env_var, "")
            if not value:
                raise EnvironmentError(
                    f"Environment variable '{env_var}' (api_key_env) is not set. "
                    f"Add it to your .env file before running."
                )
            return value

        fallback = os.environ.get("WATSONX_API_KEY", "")
        if fallback:
            return fallback

        raise EnvironmentError(
            "watsonx backend requires an IBM Cloud API key. "
            "Set api_key_env: WATSONX_API_KEY in config.yaml and export "
            "the variable in your .env file."
        )

    def _resolve_project_id(self, factory_cfg: Dict[str, Any]) -> str:
        env_var = factory_cfg.get("project_id_env", "").strip()
        if env_var:
            value = os.environ.get(env_var, "")
            if value:
                return value

        raw = factory_cfg.get("project_id", "").strip()
        if raw:
            return raw

        fallback = os.environ.get("WATSONX_PROJECT_ID", "")
        if fallback:
            return fallback

        raise EnvironmentError(
            "watsonx backend requires a project_id. Set project_id_env: "
            "WATSONX_PROJECT_ID in config.yaml and export the variable in "
            "your .env file, or set project_id directly in config.yaml."
        )
