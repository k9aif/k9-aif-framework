# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Patent Pending
# File: k9_aif_abb/k9_core/streaming/base_stream_provider.py

class BaseStreamProvider:
    def connect(self):
        raise NotImplementedError
    def subscribe(self, topic, group_id, on_message):
        raise NotImplementedError
    def publish(self, topic, message):
        raise NotImplementedError