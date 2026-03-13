# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF - Patent Pending

class MockAuth:
    def __init__(self, secret: str = "demo-secret", **kwargs):
        self.secret = secret
    def authenticate(self, token: str) -> bool:
        return token == "demo-secret"