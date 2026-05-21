# SPDX-License-Identifier: Apache-2.0

"""
K9-AIF EOC — Router Package
=============================

This package contains the **EOCModelRouter** SBB, which extends the
K9-AIF ``K9ModelRouter`` ABB with EOC-specific routing intelligence.

EOCModelRouter (eoc_model_router)
----------------------------------
Adds three routing dimensions on top of the base catalog routing:

**1. Compliance hard-gate (Guardian-required tasks)**
    Tasks of type ``pii_detection``, ``policy``, ``confidential``,
    ``guardrails``, or ``output_validation`` are unconditionally routed
    to the ``guardian`` model capability (Granite Guardian).
    No fallback model is accepted — this is a hard regulatory requirement.

**2. Cost-sensitive routing**
    Tasks of type ``summarization``, ``general``, ``chat``, or
    ``customer_intent`` are routed to the cheapest capable model first
    (Llama 3.x local via Ollama), reducing watsonx API costs for
    high-volume, commodity-quality tasks.

**3. Capability-matched routing**
    All other tasks (``reasoning``, ``adjudication``, ``extraction``,
    ``fraud``, ``audit_report``) are matched against the model catalog
    by capability string, then fall back to the catalog default.

Routing Decision Matrix
-----------------------
::

    Task Type              Primary Model      Fallback       Rationale
    ─────────────────────  ─────────────────  ─────────────  ──────────────────────────────
    adjudication/reasoning  reasoning (Granite 3.x)  general  Domain accuracy required
    pii_detection/policy    guardian (Granite Guardian)  NONE  Regulatory — hard requirement
    extraction/ocr          extraction (Granite Code)  general  Structured output
    fraud/anomaly           reasoning (Granite 3.x)  general  Complex signal correlation
    customer_intent/chat    general (Llama 3.x)  reasoning  Cost-optimized, high volume
    audit_report            reasoning (Granite 3.x)  general  Formal language accuracy
    summarization           general (Llama 3.x)  —           Commodity task

Framework Integration
---------------------
``EOCModelRouter`` is obtained via ``ModelRouterFactory.get_router(config)``.
The factory bootstraps ``LLMFactory``, builds the ``ModelCatalog`` from
``config/config.yaml``, creates the SQLite/Postgres ``RoutingStateStore``,
and returns a cached router instance.

Example Usage
-------------
::

    from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
    from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
    from k9_aif_abb.k9_utils.config_loader import load_yaml

    config = load_yaml("examples/K9X_Enterprise_Insurance_OperationsCenter/config/config.yaml")
    router = ModelRouterFactory.get_router(config)

    req = InferenceRequest(
        prompt="Evaluate this claim for policy coverage...",
        task_type="adjudication",
    )
    response = router.invoke(req)
    print(response.model_alias, response.output)
"""

