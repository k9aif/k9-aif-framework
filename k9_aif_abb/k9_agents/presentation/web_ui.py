# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Patent Pending

from k9_aif_abb.k9_core.presentation.base_ui import BaseUI

class WebUI(BaseUI):
    def render(self, response: dict) -> None:
        print("[WebUI] Rendering response (stubbed):", response)