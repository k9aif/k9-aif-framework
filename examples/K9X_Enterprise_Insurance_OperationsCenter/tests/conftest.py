# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — pytest configuration

import sys
from pathlib import Path

# Ensure repo root is on sys.path so all `examples.*` and `k9_aif_abb.*` imports resolve.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EOC_ROOT = Path(__file__).resolve().parents[1]
SQUADS_YAML = str(EOC_ROOT / "config" / "squads.yaml")
CONFIG_YAML  = str(EOC_ROOT / "config" / "config.yaml")
