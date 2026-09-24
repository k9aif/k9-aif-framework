# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# Tests: ProviderAdapterRegistry + provider adapters + LLMFactory dispatch

import os
import pytest
from unittest.mock import patch, MagicMock

from k9_aif_abb.k9_core.inference.provider_registry import ProviderAdapterRegistry
from k9_aif_abb.k9_core.inference.base_provider_adapter import BaseProviderAdapter
from k9_aif_abb.k9_core.inference.ollama_provider_adapter import OllamaProviderAdapter
from k9_aif_abb.k9_core.inference.openai_provider_adapter import OpenAIProviderAdapter
from k9_aif_abb.k9_core.inference.azure_openai_provider_adapter import AzureOpenAIProviderAdapter
from k9_aif_abb.k9_core.inference.ollama_llm import OllamaLLM
from k9_aif_abb.k9_core.inference.openai_llm import OpenAILLM
from k9_aif_abb.k9_core.inference.azure_openai_llm import AzureOpenAILLM
from k9_aif_abb.k9_factories.llm_factory import LLMFactory


# ── ProviderAdapterRegistry ────────────────────────────────────────────────

class TestProviderAdapterRegistry:

    def setup_method(self):
        ProviderAdapterRegistry.reset()

    def test_defaults_loaded_on_first_resolve(self):
        adapter = ProviderAdapterRegistry.resolve("ollama")
        assert isinstance(adapter, OllamaProviderAdapter)

    def test_openai_backend_resolves(self):
        adapter = ProviderAdapterRegistry.resolve("openai")
        assert isinstance(adapter, OpenAIProviderAdapter)

    def test_openai_compatible_backend_resolves(self):
        adapter = ProviderAdapterRegistry.resolve("openai-compatible")
        assert isinstance(adapter, OpenAIProviderAdapter)

    def test_azure_openai_backend_resolves(self):
        adapter = ProviderAdapterRegistry.resolve("azure-openai")
        assert isinstance(adapter, AzureOpenAIProviderAdapter)

    def test_unknown_backend_raises_valueerror(self):
        with pytest.raises(ValueError, match="No provider adapter registered"):
            ProviderAdapterRegistry.resolve("nonexistent-provider")

    def test_custom_adapter_registration(self):
        class CustomAdapter(BaseProviderAdapter):
            provider_name = "custom"
            def create_llm(self, model_name, factory_cfg, extra_kwargs):
                return MagicMock()

        ProviderAdapterRegistry.register("custom", CustomAdapter)
        adapter = ProviderAdapterRegistry.resolve("custom")
        assert isinstance(adapter, CustomAdapter)

    def test_register_does_not_affect_other_backends(self):
        class AnotherAdapter(BaseProviderAdapter):
            provider_name = "another"
            def create_llm(self, model_name, factory_cfg, extra_kwargs):
                return MagicMock()

        ProviderAdapterRegistry.register("another", AnotherAdapter)
        # Ollama still resolves correctly
        adapter = ProviderAdapterRegistry.resolve("ollama")
        assert isinstance(adapter, OllamaProviderAdapter)


# ── OllamaProviderAdapter ──────────────────────────────────────────────────

class TestOllamaProviderAdapter:

    def test_creates_ollama_llm(self):
        adapter = OllamaProviderAdapter()
        factory_cfg = {"base_url": "http://localhost:11434"}
        llm = adapter.create_llm("llama3.2:1b", factory_cfg, {})
        assert isinstance(llm, OllamaLLM)
        assert llm.model == "llama3.2:1b"
        assert llm.host == "http://localhost:11434"

    def test_default_base_url(self):
        adapter = OllamaProviderAdapter()
        llm = adapter.create_llm("llama3.2:1b", {}, {})
        assert llm.host == "http://localhost:11434"

    def test_extra_kwargs_forwarded(self):
        adapter = OllamaProviderAdapter()
        llm = adapter.create_llm("llama3.2:1b", {}, {"temperature": 0.1})
        assert llm.kwargs.get("temperature") == 0.1


# ── OpenAIProviderAdapter ──────────────────────────────────────────────────

class TestOpenAIProviderAdapter:

    def test_creates_openai_llm_via_api_key_env(self):
        adapter = OpenAIProviderAdapter()
        factory_cfg = {"api_key_env": "TEST_OPENAI_KEY"}
        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test-123"}):
            llm = adapter.create_llm("gpt-4o-mini", factory_cfg, {})
        assert isinstance(llm, OpenAILLM)
        assert llm.model == "gpt-4o-mini"

    def test_creates_grok_llm_with_base_url(self):
        adapter = OpenAIProviderAdapter()
        factory_cfg = {
            "api_key_env": "GROK_API_KEY",
            "base_url": "https://api.x.ai/v1",
        }
        with patch.dict(os.environ, {"GROK_API_KEY": "xai-test-456"}):
            llm = adapter.create_llm("grok-3-mini", factory_cfg, {})
        assert isinstance(llm, OpenAILLM)
        assert llm.model == "grok-3-mini"

    def test_missing_api_key_env_raises(self):
        adapter = OpenAIProviderAdapter()
        factory_cfg = {"api_key_env": "MISSING_KEY_XYZ"}
        clean_env = {k: v for k, v in os.environ.items() if k != "MISSING_KEY_XYZ"}
        with patch.dict(os.environ, clean_env, clear=True):
            with pytest.raises(EnvironmentError, match="MISSING_KEY_XYZ"):
                adapter.create_llm("gpt-4o", factory_cfg, {})

    def test_legacy_api_key_with_env_placeholder(self):
        adapter = OpenAIProviderAdapter()
        factory_cfg = {"api_key": "${MY_API_KEY}"}
        with patch.dict(os.environ, {"MY_API_KEY": "sk-legacy-789"}):
            llm = adapter.create_llm("gpt-4o-mini", factory_cfg, {})
        assert isinstance(llm, OpenAILLM)

    def test_implicit_openai_api_key_fallback(self):
        adapter = OpenAIProviderAdapter()
        factory_cfg = {}  # no api_key_env or api_key
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-implicit"}):
            llm = adapter.create_llm("gpt-4o-mini", factory_cfg, {})
        assert isinstance(llm, OpenAILLM)

    def test_no_key_at_all_raises(self):
        adapter = OpenAIProviderAdapter()
        factory_cfg = {}
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("OPENAI_API_KEY", "GROK_API_KEY")}
        with patch.dict(os.environ, clean_env, clear=True):
            with pytest.raises(EnvironmentError, match="api_key_env"):
                adapter.create_llm("gpt-4o-mini", factory_cfg, {})


# ── AzureOpenAIProviderAdapter ─────────────────────────────────────────────

class TestAzureOpenAIProviderAdapter:

    def test_creates_azure_openai_llm(self):
        adapter = AzureOpenAIProviderAdapter()
        factory_cfg = {
            "api_key_env": "TEST_AZURE_KEY",
            "azure_endpoint": "https://my-resource.openai.azure.com",
            "api_version": "2024-10-21",
        }
        with patch.dict(os.environ, {"TEST_AZURE_KEY": "azkey-test-123"}):
            llm = adapter.create_llm("gpt-4o", factory_cfg, {})
        assert isinstance(llm, AzureOpenAILLM)
        # No explicit deployment given -- falls back to model_name.
        assert llm.deployment == "gpt-4o"

    def test_explicit_deployment_overrides_model_name(self):
        """Enterprises frequently name a deployment differently from the
        underlying model (e.g. "prod-gpt4o-eastus2" serving gpt-4o)."""
        adapter = AzureOpenAIProviderAdapter()
        factory_cfg = {
            "api_key_env": "TEST_AZURE_KEY",
            "azure_endpoint": "https://my-resource.openai.azure.com",
        }
        with patch.dict(os.environ, {"TEST_AZURE_KEY": "azkey-test-123"}):
            llm = adapter.create_llm("gpt-4o", factory_cfg, {"deployment": "prod-gpt4o-eastus2"})
        assert llm.deployment == "prod-gpt4o-eastus2"

    def test_default_api_version_applied(self):
        adapter = AzureOpenAIProviderAdapter()
        factory_cfg = {
            "api_key_env": "TEST_AZURE_KEY",
            "azure_endpoint": "https://my-resource.openai.azure.com",
        }
        with patch.dict(os.environ, {"TEST_AZURE_KEY": "azkey-test-123"}):
            llm = adapter.create_llm("gpt-4o", factory_cfg, {})
        assert isinstance(llm, AzureOpenAILLM)  # construction itself proves a version resolved

    def test_missing_api_key_env_raises(self):
        adapter = AzureOpenAIProviderAdapter()
        factory_cfg = {
            "api_key_env": "MISSING_AZURE_KEY_XYZ",
            "azure_endpoint": "https://my-resource.openai.azure.com",
        }
        clean_env = {k: v for k, v in os.environ.items() if k != "MISSING_AZURE_KEY_XYZ"}
        with patch.dict(os.environ, clean_env, clear=True):
            with pytest.raises(EnvironmentError, match="MISSING_AZURE_KEY_XYZ"):
                adapter.create_llm("gpt-4o", factory_cfg, {})

    def test_missing_endpoint_raises(self):
        adapter = AzureOpenAIProviderAdapter()
        factory_cfg = {"api_key_env": "TEST_AZURE_KEY"}  # no azure_endpoint
        clean_env = {k: v for k, v in os.environ.items() if k != "AZURE_OPENAI_ENDPOINT"}
        with patch.dict(os.environ, {**clean_env, "TEST_AZURE_KEY": "azkey-test"}, clear=True):
            with pytest.raises(EnvironmentError, match="azure_endpoint"):
                adapter.create_llm("gpt-4o", factory_cfg, {})

    def test_implicit_azure_openai_api_key_fallback(self):
        adapter = AzureOpenAIProviderAdapter()
        factory_cfg = {"azure_endpoint": "https://my-resource.openai.azure.com"}
        with patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "azkey-implicit"}):
            llm = adapter.create_llm("gpt-4o", factory_cfg, {})
        assert isinstance(llm, AzureOpenAILLM)

    def test_implicit_azure_openai_endpoint_fallback(self):
        adapter = AzureOpenAIProviderAdapter()
        factory_cfg = {"api_key_env": "TEST_AZURE_KEY"}
        with patch.dict(os.environ, {
            "TEST_AZURE_KEY": "azkey-test",
            "AZURE_OPENAI_ENDPOINT": "https://implicit-resource.openai.azure.com",
        }):
            llm = adapter.create_llm("gpt-4o", factory_cfg, {})
        assert isinstance(llm, AzureOpenAILLM)


# ── LLMFactory dispatch via registry ──────────────────────────────────────

class TestLLMFactoryProviderDispatch:

    def setup_method(self):
        LLMFactory.reset()
        ProviderAdapterRegistry.reset()

    def _ollama_config(self):
        return {
            "inference": {
                "llm_factory": {
                    "backend": "ollama",
                    "base_url": "http://localhost:11434",
                    "models": {
                        "general": {"model": "llama3.2:1b", "temperature": 0.3}
                    },
                }
            }
        }

    def _openai_config(self, env_var="OPENAI_API_KEY"):
        return {
            "inference": {
                "llm_factory": {
                    "backend": "openai",
                    "api_key_env": env_var,
                    "models": {
                        "general": {"model": "gpt-4o-mini", "temperature": 0.3}
                    },
                }
            }
        }

    def _grok_config(self):
        return {
            "inference": {
                "llm_factory": {
                    "backend": "openai-compatible",
                    "base_url": "https://api.x.ai/v1",
                    "api_key_env": "GROK_API_KEY",
                    "models": {
                        "general": {"model": "grok-3-mini", "temperature": 0.3}
                    },
                }
            }
        }

    def _azure_openai_config(self):
        return {
            "inference": {
                "llm_factory": {
                    "backend": "azure-openai",
                    "azure_endpoint": "https://my-resource.openai.azure.com",
                    "api_key_env": "AZURE_TEST_KEY",
                    "models": {
                        "general": {"model": "gpt-4o", "temperature": 0.3}
                    },
                }
            }
        }

    def test_ollama_backend_creates_ollama_llm(self):
        LLMFactory.bootstrap(self._ollama_config())
        llm = LLMFactory.get("general")
        assert isinstance(llm, OllamaLLM)

    def test_openai_backend_creates_openai_llm(self):
        LLMFactory.bootstrap(self._openai_config())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            llm = LLMFactory.get("general")
        assert isinstance(llm, OpenAILLM)
        assert llm.model == "gpt-4o-mini"

    def test_grok_backend_creates_openai_llm_with_base_url(self):
        LLMFactory.bootstrap(self._grok_config())
        with patch.dict(os.environ, {"GROK_API_KEY": "xai-test"}):
            llm = LLMFactory.get("general")
        assert isinstance(llm, OpenAILLM)
        assert llm.model == "grok-3-mini"

    def test_azure_openai_backend_creates_azure_openai_llm(self):
        LLMFactory.bootstrap(self._azure_openai_config())
        with patch.dict(os.environ, {"AZURE_TEST_KEY": "azkey-test"}):
            llm = LLMFactory.get("general")
        assert isinstance(llm, AzureOpenAILLM)
        assert llm.deployment == "gpt-4o"

    def test_llm_instances_are_cached(self):
        LLMFactory.bootstrap(self._ollama_config())
        a = LLMFactory.get("general")
        b = LLMFactory.get("general")
        assert a is b

    def test_custom_adapter_used_by_factory(self):
        """Future provider: register custom adapter, factory uses it automatically."""
        class FakeLLM(OllamaLLM):
            pass

        class FakeAdapter(BaseProviderAdapter):
            provider_name = "fake"
            def create_llm(self, model_name, factory_cfg, extra_kwargs):
                return FakeLLM(host="http://fake", model=model_name)

        ProviderAdapterRegistry.register("fake", FakeAdapter)
        cfg = {
            "inference": {
                "llm_factory": {
                    "backend": "fake",
                    "models": {"general": {"model": "fake-model"}},
                }
            }
        }
        LLMFactory.bootstrap(cfg)
        llm = LLMFactory.get("general")
        assert isinstance(llm, FakeLLM)

    def test_public_api_unchanged(self):
        """Verify existing public surface: bootstrap, get, get_model, reset."""
        LLMFactory.bootstrap(self._ollama_config())
        assert LLMFactory.is_bootstrapped()
        assert LLMFactory.get_model("general") == "llama3.2:1b"
        llm = LLMFactory.get("general")
        assert llm is not None
        LLMFactory.reset()
        assert not LLMFactory.is_bootstrapped()
