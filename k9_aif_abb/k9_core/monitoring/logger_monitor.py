# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

class LoggerMonitor:
    def __init__(self, **kwargs):
        pass
    def log(self, message: str) -> None:
        print(f"[LOGGER MONITOR] {message}")

    def record_event(self, event: dict) -> None:
        """Same contract as BaseMonitor.record_event() (1.23.1)."""
        self.log(f"event {event.get('type') or event.get('status') or 'event'}: {event}")