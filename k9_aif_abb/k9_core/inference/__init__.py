# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
k9_core.inference — LLM inference ABB contracts.

BaseLLM
    Abstract base for all LLM adapters. Defines the ``generate(prompt, system_prompt=None)``
    contract. The ``system_prompt`` parameter separates system-level instructions (agent role,
    persona, constraints) from user-level content (the task payload). Providers that support
    a dedicated system channel (Ollama ``system``, Claude ``system``, OpenAI ``system`` role)
    use it directly; others prepend it to the prompt.

    Keeping the system prompt separate enables prompt caching — the system portion is stable
    across calls and cacheable independently of per-request user content.

OllamaLLM
    OOB adapter for Ollama. Passes ``system_prompt`` as the Ollama API's ``system`` field,
    keeping it separate from the user ``prompt``.
"""
