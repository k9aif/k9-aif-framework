# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_factories/model_router_factory.py

import logging
from typing import Dict, Any

from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_aif_abb.k9_inference.catalog.model_catalog import ModelCatalog
from k9_aif_abb.k9_inference.routers.base_model_router import BaseModelRouter
from k9_aif_abb.k9_inference.routers.default_model_router import DefaultModelRouter
from k9_aif_abb.k9_inference.routers.k9_model_router import K9ModelRouter


class ModelRouterFactory:
    """
    K9-AIF Factory ABB - ModelRouterFactory
    ---------------------------------------
    Responsible for provisioning model router instances.

    Responsibilities:
      - read inference router config
      - build model catalog
      - instantiate configured router implementation
      - cache router instances if needed
    """

    _instances: Dict[str, BaseModelRouter] = {}
    logger = logging.getLogger("ModelRouterFactory")

    @classmethod
    def get_router(cls, config: Dict[str, Any]) -> BaseModelRouter:
        """
        Return a configured model router instance.

        Expected config patterns:
          1. Nested:
             inference:
               router:
                 type: k9
               model_catalog:
                 ...
          2. Flattened:
             router:
               type: k9
             model_catalog:
               ...
        """
        cfg = cls._normalize_config(config)

        inf_cfg = cfg.get("inference", {})
        router_cfg = inf_cfg.get("router", {})
        router_type = (router_cfg.get("type") or "k9").lower()

        if not LLMFactory.is_bootstrapped():
            LLMFactory.bootstrap(config)

        cache_key = router_type
        if cache_key in cls._instances:
            return cls._instances[cache_key]

        catalog = cls._build_catalog(cfg)

        if router_type == "k9":
            router = K9ModelRouter(catalog)

        elif router_type == "default":
            default_alias = router_cfg.get("default_model_alias", "general")
            router = DefaultModelRouter(default_alias)

        else:
            raise ValueError(f"Unsupported router type: {router_type}")

        cls._instances[cache_key] = router
        cls.logger.info(f"Router ready -> {router.__class__.__name__}")
        return router

    @classmethod
    def _normalize_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize flattened config to inference.* shape.
        """
        if "inference" not in config and any(
            k in config for k in ("router", "model_catalog", "llm_factory")
        ):
            return {
                "inference": {
                    "router": config.get("router", {}),
                    "model_catalog": config.get("model_catalog", {}),
                    "llm_factory": config.get("llm_factory", {}),
                }
            }

        return config

    @classmethod
    def _build_catalog(cls, config: Dict[str, Any]) -> ModelCatalog:
        """
        Build ModelCatalog from config.

        Preferred config:
          inference:
            model_catalog:
              default_model: general
              models:
                general:
                  provider: ollama
                  llm_ref: general
                  capabilities: [chat]
                confidential:
                  provider: watsonx
                  llm_ref: secure_general
                  capabilities: [confidential]

        Fallback:
          derive minimal catalog from inference.llm_factory.models
        """
        inf_cfg = config.get("inference", {})
        catalog_cfg = inf_cfg.get("model_catalog", {})

        if not catalog_cfg:
            llm_cfg = inf_cfg.get("llm_factory", {})
            llm_models = llm_cfg.get("models", {}) or {}

            derived_models = {
                alias: {
                    "provider": llm_cfg.get("provider", "ollama"),
                    "llm_ref": alias,
                    "capabilities": [alias],
                }
                for alias in llm_models
            }

            default_model = (
                "general"
                if "general" in derived_models
                else next(iter(derived_models), None)
            )

            catalog_cfg = {
                "default_model": default_model,
                "models": derived_models,
            }

            cls.logger.info(
                "[ModelRouterFactory] model_catalog missing; derived minimal catalog from llm_factory.models"
            )

        return ModelCatalog(catalog_cfg)

    @classmethod
    def reset(cls) -> None:
        cls._instances.clear()
        cls.logger.info("ModelRouterFactory reset complete.")