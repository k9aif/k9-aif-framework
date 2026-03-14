import yaml

from k9_aif_abb.k9_inference.catalog.model_catalog import ModelCatalog
from k9_aif_abb.k9_inference.routers.k9_model_router import K9ModelRouter
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_factories.llm_factory import LLMFactory


# ------------------------------------------------------------
# Load config.yaml
# ------------------------------------------------------------
with open("k9_aif_abb/config/config.yaml", "r") as f:
    config = yaml.safe_load(f)


# ------------------------------------------------------------
# Initialize catalog and router
# ------------------------------------------------------------
LLMFactory.bootstrap(config)
catalog = ModelCatalog(config)
router = K9ModelRouter(catalog)


# ------------------------------------------------------------
# Create request
# ------------------------------------------------------------
req = InferenceRequest(
    prompt="Who is Elon Musk?",
    task_type="chat"
)


# ------------------------------------------------------------
# Invoke router
# ------------------------------------------------------------
response = router.invoke(req)

print(response)