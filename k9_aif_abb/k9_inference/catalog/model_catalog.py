from typing import Dict, Any


class ModelCatalog:
    """
    Loads model definitions from config.yaml and exposes them to routers.
    """

    def __init__(self, config: Dict[str, Any]):
        inference_cfg = config.get("inference", {})
        self.router_cfg = inference_cfg.get("router", {})
        self.models = inference_cfg.get("models", {})

    def get_default_model(self) -> str:
        return self.router_cfg.get("default_model")

    def get_model(self, alias: str) -> Dict[str, Any]:
        return self.models.get(alias, {})

    def list_models(self):
        return list(self.models.keys())

    def find_by_capability(self, capability: str):
        for alias, meta in self.models.items():
            caps = meta.get("capabilities", [])
            if capability in caps:
                return alias
        return None