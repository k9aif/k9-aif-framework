"""
K9-AIF Integration Adapters — deterministic, non-agentic connectors to external
enterprise systems. These are ABB contracts; SBBs are registered via
IntegrationAdapterFactory.register().
"""

from .base_integration_adapter import BaseIntegrationAdapter
from .base_api_adapter import BaseApiAdapter
from .base_messaging_adapter import BaseMessagingAdapter
from .base_rules_adapter import BaseRulesAdapter
from .base_workflow_adapter import BaseWorkflowAdapter
from .base_process_flow_adapter import BaseProcessFlowAdapter
from .base_bpm_adapter import BaseBpmAdapter
from .base_data_adapter import BaseDataAdapter
from .integration_adapter_factory import IntegrationAdapterFactory

__all__ = [
    "BaseIntegrationAdapter",
    "BaseApiAdapter",
    "BaseMessagingAdapter",
    "BaseRulesAdapter",
    "BaseWorkflowAdapter",
    "BaseProcessFlowAdapter",
    "BaseBpmAdapter",
    "BaseDataAdapter",
    "IntegrationAdapterFactory",
]
