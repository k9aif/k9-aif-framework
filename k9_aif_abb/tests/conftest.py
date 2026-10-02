# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Unit tests run in the test environment.

K9_ENV unset means production, where an ungoverned agent refuses to run
(BaseAgent governance by construction). Most tests here build agents
without a governance pipeline on purpose, so the suite defaults to
K9_ENV=test; an explicit K9_ENV still wins, and the production behaviour
is tested explicitly in test_governance_by_construction.py.
"""

import os

os.environ.setdefault("K9_ENV", "test")
