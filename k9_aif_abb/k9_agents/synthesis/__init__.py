# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Squad coordinator synthesizer: condenses a squad's accumulated results
into a digest for the next agent (BaseSquad ``synthesis:``, 1.16)."""

from .context_synthesizer_agent import K9ContextSynthesizerAgent

__all__ = ["K9ContextSynthesizerAgent"]
