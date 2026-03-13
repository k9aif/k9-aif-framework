# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Patent Pending

from k9_aif_abb.k9_core.logging.base_logger import BaseLoggingAgent

class ConsoleLoggingAgent(BaseLoggingAgent):
    def log(self, message: str, level: str = "INFO"):
        print(f"[{self.name}] {level}: {message}")