# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""Errors raised by the factories when a process is given conflicting configuration."""


class ConfigConflictError(ValueError):
    """A factory already set up in this process was given a different configuration.

    Factories keep one configuration per process (K9-AIF runs one application per
    process). A second, different configuration used to be ignored silently, so the first
    one won without a word; now it is refused. In tests, reset the factories between
    configurations (``k9_aif_abb.k9_factories.reset_all()``).
    """
