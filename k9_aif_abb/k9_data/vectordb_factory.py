# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Patent Pending
# k9_aif_abb/k9_data/vectordb_factory.py

import importlib
from k9_aif_abb.k9_data.base_vectordb import BaseVectorDB

class VectorDBFactory:
    @staticmethod
    def from_config(cfg: dict) -> BaseVectorDB:
        vdb_cfg = cfg.get("vectordb", {}) or {}
        provider = vdb_cfg.get("provider")
        module = vdb_cfg.get("module")   # full import path
        class_name = vdb_cfg.get("class")

        if not module or not class_name:
            raise ValueError("VectorDB config requires 'module' and 'class'")

        mod = importlib.import_module(module)
        cls = getattr(mod, class_name)
        return cls(vdb_cfg)