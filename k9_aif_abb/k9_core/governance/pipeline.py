# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary

class NoopGovernance:
    """Default governance pipeline that does nothing."""

    def pre_process(self, payload: dict, ctx: dict | None = None) -> dict:
        return payload

    def post_process(self, payload: dict, ctx: dict | None = None) -> dict:
        return payload