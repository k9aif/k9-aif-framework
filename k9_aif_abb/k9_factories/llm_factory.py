# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# File: k9_aif_abb/k9_factories/llm_factory.py

import logging
import yaml
import os
import traceback
from typing import Dict, Any, Optional
from k9_aif_abb.k9_core.inference.ollama_llm import OllamaLLM


class LLMFactory:
    """
    K9-AIF Factory ABB - LLMFactory
    -------------------------------
    Unified model manager for Granite / Ollama / watsonx.ai models.

    Backward-compatible with older agents expecting:
      - LLMFactory.is_bootstrapped
      - LLMFactory._models
      - LLMFactory.get_model()
    """

    # ------------------------------------------------------------------
    # Internal state
    # ------------------------------------------------------------------
    _bootstrapped: bool = False
    _cfg: Dict[str, Any] = {}
    _instances: Dict[str, Any] = {}

    # Legacy compatibility (for AdvisorAgent, etc.)
    _models: Dict[str, str] = {}
    _is_bootstrapped: bool = False  # internal flag for callable property

    # ------------------------------------------------------------------
    # Callable compatibility shim
    # ------------------------------------------------------------------
    @classmethod
    def is_bootstrapped(cls) -> bool:
        """Legacy callable compatibility (for old agents)."""
        return cls._bootstrapped or cls._is_bootstrapped

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------
    @classmethod
    def bootstrap(cls, config):
        """Initialize the LLM factory (supports ABB + SBB flattened configs)."""
        try:
            # Normalize structure for flattened SBB configs
            if "inference" not in config and "llm_factory" in config:
                print("[LLMFactory] [INFO] Normalizing flattened config -> nesting under inference.llm_factory")
                config = {"inference": {"llm_factory": config["llm_factory"]}}

            llm_cfg = config.get("inference", {}).get("llm_factory", {})
            if not llm_cfg:
                raise ValueError("[LLMFactory] [ERROR] Missing inference.llm_factory section in config")

            # [OK] FIX: Store the entire config in cls._cfg
            cls._cfg = config
            cls._bootstrapped = True
            cls._is_bootstrapped = True
            
            # [OK] FIX: Populate cls._models for legacy compatibility
            cls._models = llm_cfg.get("models", {})
            
            # Store configuration attributes
            cls.backend = llm_cfg.get("backend", "ollama")
            cls.provider = llm_cfg.get("provider", "ollama")
            cls.base_url = llm_cfg.get("base_url", "")

            print(f"[LLMFactory] [INFO] Loaded models -> {cls._models}")
            print(f"[LLMFactory] [INFO] Base URL -> {cls.base_url}")
            print(f"[LLMFactory] [OK] Provider -> {cls.provider}")
            print(f"[LLMFactory] [OK] Bootstrap complete")

        except Exception as e:
            print(f"[LLMFactory] [ERROR] Bootstrap failed: {e}")
            traceback.print_exc()
            raise
             
    # ------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------
    @classmethod
    def get(cls, alias: Optional[str] = "general") -> OllamaLLM:
        """
        Return a cached or newly constructed OllamaLLM instance for the alias.
        Defensive default ensures alias='general' if None is passed.
        """
        alias = alias or "general"  # safeguard for agents passing None

        if alias in cls._instances:
            return cls._instances[alias]

        if not cls._bootstrapped:
            raise RuntimeError("LLMFactory.get() called before bootstrap().")

        log = logging.getLogger("LLMFactory")

        inf = (cls._cfg or {}).get("inference", {})
        fcfg = inf.get("llm_factory") or {}
        base_url = fcfg.get("base_url", "http://localhost:11434")
        model_id = (fcfg.get("models") or {}).get(alias)

        if not model_id:
            raise KeyError(
                f"LLM model alias '{alias}' is not configured under inference.llm_factory.models"
            )

        # Quiet initialization (no announce)
        inst = OllamaLLM(host=base_url, model=model_id)
        cls._instances[alias] = inst
        log.info(f"LLM instance ready [{alias} -> {model_id}] (cached).")

        return inst

    # ------------------------------------------------------------------
    # Legacy accessor (for older agents)
    # ------------------------------------------------------------------
    @classmethod
    def get_model(cls, name: str = "general") -> Optional[str]:
        """Return model identifier by logical name (legacy use)."""
        if not cls.is_bootstrapped():
            logging.getLogger("LLMFactory").warning(
                "get_model() called before bootstrap"
            )
        return cls._models.get(name)

    # ------------------------------------------------------------------
    # Reset (for tests or reloads)
    # ------------------------------------------------------------------
    @classmethod
    def reset(cls):
        """Clear all loaded models and reset bootstrap flag."""
        cls._instances.clear()
        cls._bootstrapped = False
        cls._is_bootstrapped = False
        cls._cfg = {}
        cls._models = {}
        logging.getLogger("LLMFactory").info("LLMFactory reset complete.")