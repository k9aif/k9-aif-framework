# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""Messaging failures that must stop a process rather than lose events."""


class MessagingUnavailableError(RuntimeError):
    """The configured message bus (Kafka / Redpanda) cannot be reached.

    Raised in production (``K9_ENV`` unset, ``production`` or anything other than
    development/dev/test) when the bus cannot be connected at start-up. Running on without
    it would drop every published event while the application looked healthy. In
    development and test the bus degrades with a warning instead.
    """


class LargeEventError(RuntimeError):
    """An event over ``max_event_bytes`` could not be stored in object storage (so it was not sent),
    or a consumer could not fetch a stored event back (expired, deleted, unreachable, hash mismatch)."""
