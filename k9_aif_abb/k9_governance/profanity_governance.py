# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
ProfanityGovernance — retired in place, 2026-09-19.

The original implementation here was example/placeholder code (its own
docstring said so) and was confirmed non-functional against the real
model: it read payload["text"] (generated agents use "query"), used a
prompt instructing the model to answer "SAFE"/"BLOCKED" free text, and
granite4.1-guardian:8b never actually produces that format — it always
answers "<score>yes</score>"/"<score>no</score>" regardless of prompt
wording (confirmed empirically, see k9x_satan/target/guardian_governance.py,
where this was first discovered and correctly handled). Against the real
model, the old pre_process()'s `"BLOCKED" in result.upper()` check could
never match, so it would silently pass every payload, safe or not,
forever — while looking like semantic governance was active.

Both generator templates (studiox_v2's and studiox_ibm's
agent_base.py.j2/agent_critic_actor.py.j2/agent_validation_loop.py.j2) and
every scaffold either has already generated construct this exact class by
name — `from k9_aif_abb.k9_governance.profanity_governance import
ProfanityGovernance`. Rather than rename the class and require touching
every generator template and already-generated scaffold, this file now
re-exports the real, fixed implementation under the same name — every
existing call site keeps working unchanged, and starts actually working
correctly instead of silently doing nothing. See guardian_governance.py
for the real implementation and its full docstring.
"""

from k9_aif_abb.k9_governance.guardian_governance import GuardianGovernance

ProfanityGovernance = GuardianGovernance
