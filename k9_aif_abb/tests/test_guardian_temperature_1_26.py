# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""1.26: Granite Guardian's ingress/egress classification is sent with temperature 0 (configurable), so the
same content gets the same verdict on every run. Before 1.26 no temperature was sent (Ollama default sampling)."""
from unittest.mock import patch

from k9_aif_abb.k9_governance.guardian_governance import GuardianGovernance


class _Resp:
    status_code = 200
    ok = True

    def json(self):
        return {"response": "<score> no </score>"}

    def raise_for_status(self):
        return None


def _sent_options(cfg):
    sent = {}

    def fake_post(url, json=None, **kw):
        sent.update(json or {})
        return _Resp()
    gov = GuardianGovernance(cfg)
    with patch("k9_aif_abb.k9_governance.guardian_governance.requests.post", side_effect=fake_post):
        gov.pre_process({"query": "hello"}, {"layer": "t"})
    return sent.get("options")


def test_default_temperature_is_zero():
    assert _sent_options({}) == {"temperature": 0.0}


def test_temperature_is_configurable():
    assert _sent_options({"governance": {"guardian": {"temperature": 0.7}}}) == {"temperature": 0.7}
