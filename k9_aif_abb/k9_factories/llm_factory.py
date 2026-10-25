# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_factories/llm_factory.py

import hashlib
import json
import logging
import threading
from typing import Dict, Any, Optional

from k9_aif_abb.k9_core.inference.base_llm import BaseLLM
from k9_aif_abb.k9_factories.factory_errors import ConfigConflictError

log = logging.getLogger("LLMFactory")

# Keys of a model alias that tune the model itself. Every other key of the alias (base_url, api_version,
# deployment, api_key_env, ...) is a connection setting that overrides the factory-wide one for this model.
_MODEL_PARAMS = ("model", "backend", "provider", "temperature", "max_tokens", "num_ctx", "think", "timeout",
                 "digest", "digest_recheck_seconds")


def _llm_section(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The inference.llm_factory section of a nested or flattened config, or None if it has none."""
    config = config or {}
    if "inference" not in config and "llm_factory" in config:
        return config.get("llm_factory") or None
    return (config.get("inference") or {}).get("llm_factory") or None


def _fingerprint(section: Any) -> str:
    return hashlib.sha256(json.dumps(section, sort_keys=True, default=str).encode()).hexdigest()


class LLMFactory:
    """
    K9-AIF Factory ABB - LLMFactory
    -------------------------------
    Unified model manager for configured LLM backends.

    Each model alias resolves its backend in this order: the alias's own ``backend`` (or
    ``provider``) key, then the factory-wide ``backend`` (or ``provider``), then ``ollama``.
    So local and hosted models can serve side by side; an alias's own connection keys
    (``base_url``, ``api_version``, ``deployment``, ``api_key_env``...) override the factory-wide
    ones for that alias. Secrets stay in the environment.

        inference:
          llm_factory:
            backend: ollama                 # default for every alias
            base_url: http://localhost:11434
            models:
              general: llama3
              auditor:
                backend: watsonx            # this alias only
                model: ibm/granite-3-8b-instruct
                base_url: https://us-south.ml.cloud.ibm.com

    One configuration per process (K9-AIF runs one application per process). Bootstrapping
    again with the same ``inference.llm_factory`` section is a no-op; a different one raises
    :class:`ConfigConflictError` instead of being half-applied. Tests reset between
    configurations with :meth:`reset`.

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
    _fingerprint: Optional[str] = None
    _instances: Dict[str, Any] = {}
    _lock = threading.RLock()

    # Legacy compatibility (for AdvisorAgent, etc.)
    _models: Dict[str, Any] = {}
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
        llm_cfg = _llm_section(config)
        if not llm_cfg:
            raise ValueError("[LLMFactory] Missing inference.llm_factory section in config")
        fingerprint = _fingerprint(llm_cfg)

        with cls._lock:
            if cls._bootstrapped:
                if fingerprint == cls._fingerprint:
                    return          # same configuration again: nothing to do
                raise ConfigConflictError(
                    "LLMFactory is already set up with a different inference.llm_factory configuration in "
                    "this process. K9-AIF runs one application per process, with one configuration; an "
                    "agent's own YAML must not carry a different inference section. In tests, call "
                    "LLMFactory.reset() (or k9_aif_abb.k9_factories.reset_all()) between configurations.")

            cls._cfg = {"inference": {"llm_factory": llm_cfg}}
            cls._fingerprint = fingerprint
            cls._bootstrapped = True
            cls._is_bootstrapped = True

            # Keep raw models config for backward compatibility
            cls._models = llm_cfg.get("models", {})

            # Store configuration attributes
            cls.backend = llm_cfg.get("backend", "ollama")
            cls.provider = llm_cfg.get("provider", "ollama")
            cls.base_url = llm_cfg.get("base_url", "")

        log.info("[LLMFactory] bootstrapped: default backend %s, models %s",
                 cls.default_backend(), list(cls._models))

    @classmethod
    def ensure_bootstrapped(cls, config) -> None:
        """Bootstrap from *config* if needed, and refuse a conflicting one.

        A config with no inference.llm_factory section (an agent's config that carries none) uses
        what is already set up.
        """
        if _llm_section(config) is None and cls.is_bootstrapped():
            return
        cls.bootstrap(config)

    # ------------------------------------------------------------------
    # Backend resolution
    # ------------------------------------------------------------------
    @classmethod
    def default_backend(cls) -> str:
        fcfg = (cls._cfg or {}).get("inference", {}).get("llm_factory") or {}
        return (fcfg.get("backend") or fcfg.get("provider") or "ollama").lower()

    @classmethod
    def backend_for(cls, alias: str) -> str:
        """The backend that serves *alias*: its own setting, else the factory default, else ollama."""
        model_cfg = ((cls._cfg or {}).get("inference", {}).get("llm_factory") or {}).get("models", {}).get(alias)
        if isinstance(model_cfg, dict):
            own = model_cfg.get("backend") or model_cfg.get("provider")
            if own:
                return str(own).lower()
        return cls.default_backend()

    # ------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------
    @classmethod
    def get(cls, alias: Optional[str] = "general") -> BaseLLM:
        """
        Return a cached or newly constructed LLM instance for the alias.

        Supports both:
          1) legacy string model config:
             models:
               general: llama3

          2) structured dict model config:
             models:
               general:
                 provider: ollama
                 model: llama3.2:1b
                 temperature: 0.2
                 max_tokens: 2048
        """
        alias = alias or "general"

        if alias in cls._instances:
            return cls._instances[alias]

        with cls._lock:
            if alias in cls._instances:             # built by another thread meanwhile
                return cls._instances[alias]

            if not cls._bootstrapped:
                raise RuntimeError("LLMFactory.get() called before bootstrap().")

            fcfg = (cls._cfg or {}).get("inference", {}).get("llm_factory") or {}
            model_cfg = (fcfg.get("models") or {}).get(alias)

            if not model_cfg:
                raise KeyError(
                    f"LLM model alias '{alias}' is not configured under inference.llm_factory.models"
                )

            conn_cfg = fcfg
            # Backward-compatible handling
            if isinstance(model_cfg, str):
                model_name = model_cfg
                extra_kwargs = {}

            elif isinstance(model_cfg, dict):
                model_name = model_cfg.get("model")
                if not model_name:
                    raise KeyError(
                        f"LLM model alias '{alias}' is missing required key 'model'"
                    )

                extra_kwargs = {
                    "temperature": model_cfg.get("temperature"),
                    "max_tokens": model_cfg.get("max_tokens"),
                    "num_ctx": model_cfg.get("num_ctx"),
                    "think": model_cfg.get("think"),
                    # Seconds for one call. Large local models need more than the
                    # adapter default (OllamaLLM: 120 s) for long prompts or a cold load.
                    "timeout": model_cfg.get("timeout"),
                }
                extra_kwargs = {k: v for k, v in extra_kwargs.items() if v is not None}
                # Model integrity (1.18.6): a pinned digest, checked by the provider before each prompt.
                if model_cfg.get("digest"):
                    extra_kwargs["digest"] = model_cfg["digest"]
                    if model_cfg.get("digest_recheck_seconds") is not None:
                        extra_kwargs["digest_recheck_seconds"] = model_cfg["digest_recheck_seconds"]
                # This alias's own connection settings override the factory-wide ones.
                own_conn = {k: v for k, v in model_cfg.items() if k not in _MODEL_PARAMS}
                if own_conn:
                    conn_cfg = {**{k: v for k, v in fcfg.items() if k != "models"}, **own_conn}

            else:
                raise TypeError(
                    f"LLM model alias '{alias}' must be a string or dict, got {type(model_cfg).__name__}"
                )

            backend = cls.backend_for(alias)

            from k9_aif_abb.k9_core.inference.provider_registry import ProviderAdapterRegistry
            if "digest" in extra_kwargs and backend != "ollama":
                raise ValueError(f"LLM model alias '{alias}': 'digest' pins a locally served model and is "
                                 f"supported for the ollama backend only (backend is '{backend}')")
            adapter = ProviderAdapterRegistry.resolve(backend)
            inst = adapter.create_llm(model_name, conn_cfg, extra_kwargs)
            cls._instances[alias] = inst
            log.info("LLM instance ready [%s -> %s via %s] (cached).", alias, model_name, backend)

            return inst

    # ------------------------------------------------------------------
    # Legacy accessor (for older agents)
    # ------------------------------------------------------------------
    @classmethod
    def get_model(cls, name: str = "general") -> Optional[str]:
        """Return model identifier by logical name (legacy use)."""
        if not cls.is_bootstrapped():
            log.warning("get_model() called before bootstrap")

        model_cfg = cls._models.get(name)
        if isinstance(model_cfg, dict):
            return model_cfg.get("model")
        return model_cfg

    # ------------------------------------------------------------------
    # Reset (for tests or reloads)
    # ------------------------------------------------------------------
    @classmethod
    def reset(cls):
        """Clear all loaded models and reset bootstrap flag."""
        with cls._lock:
            cls._instances.clear()
            cls._bootstrapped = False
            cls._is_bootstrapped = False
            cls._cfg = {}
            cls._fingerprint = None
            cls._models = {}
        log.info("LLMFactory reset complete.")
