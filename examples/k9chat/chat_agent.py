# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from k9_aif_abb.k9_utils.config_loader import load_yaml
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_factories.cache_factory import CacheFactory
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke_stream
from examples.k9chat.guard_agent import GuardAgent

BASE_DIR = os.path.dirname(__file__)

# Two independent dials -- attitude/intensity and literal swearing are not
# the same axis (you can be sharply blunt with zero profanity, or mildly
# irreverent with the occasional "damn"). Both only ever change the *style
# instruction* prepended to the prompt; neither touches retrieval,
# governance, or the guard check above (guard_agent still runs on the raw
# user message regardless of where these sliders sit).
UNHINGED_INSTRUCTIONS = {
    0: "",  # default -- no injected style instruction at all
    1: "Attitude: casual and relaxed, like a helpful colleague, not corporate.",
    2: "Attitude: blunt and direct. Skip hedging and disclaimers. Say what you actually think.",
    3: "Attitude: irreverent, sharp-tongued, opinionated. No corporate hedging at all.",
    4: "Attitude: unhinged extreme. Loud, chaotic energy, zero filter on attitude. Still answer the actual question correctly -- being unhinged is a style choice, not an excuse to be wrong or to dodge what was asked.",
}

PROFANITY_INSTRUCTIONS = {
    0: "",  # default -- no instruction, don't specifically invite profanity
    1: "Occasional mild profanity is fine if it fits naturally (e.g. 'damn', 'hell').",
    2: "Profanity is fine and expected in moderation where it fits naturally.",
    3: "Heavy profanity is encouraged, including strong swear words, where it fits naturally.",
    4: "Maximum profanity -- swear as much as feels natural, no restraint at all.",
}

# A real style instruction, same mechanism as the two above -- NOT a hard
# token cap. K9ModelRouter.invoke() doesn't read InferenceRequest.max_tokens
# at all (confirmed 2026-09-20 reading k9_model_router.py directly -- a
# real, separate framework gap), so this can shorten/lengthen output the
# same way prompting always does, but can't truncate a model that decides
# to run long anyway. 1 (Short) is the meaningfully different end; 2 (Long)
# is a soft nudge more than a guarantee -- most models are already fairly
# verbose by default, so "be thorough" moves the needle less than "be
# brief" does.
LENGTH_INSTRUCTIONS = {
    0: "Keep your answer short -- one or two sentences, no more, no padding.",
    1: "",  # default -- no injected instruction, model's natural length
    2: "Give a thorough, detailed answer -- don't hold back on depth or examples.",
}

# Always-on product scope, not a slider -- unlike the three dials above,
# this isn't optional or user-controlled. K9Chat is scoped to K9-AIF/K9X,
# not a general-purpose code or image generator; a real cost concern too
# (an unrelated "write me a full game" request is a long, expensive
# generation with zero connection to what this tool is for). This is a
# soft instruction, same mechanism as the dials -- genuinely changes
# behavior (verified), but isn't a hard technical block; a determined
# adversarial prompt could still talk the model around it. A real block
# would need a pre-LLM classifier/rule-based filter, with its own real
# false-positive/negative tradeoffs -- not built, this is the honest
# first line of defense, not a guarantee.
SCOPE_INSTRUCTION = (
    "You are K9Chat, scoped specifically to the K9-AIF framework and the "
    "K9X ecosystem. Code examples are welcome, but only when they're about "
    "using or extending K9-AIF (agents, orchestrators, squads, ABBs/SBBs, "
    "K9X tools). Decline requests for general-purpose code with no K9-AIF "
    "connection (games, unrelated scripts/apps) and decline any request to "
    "generate an image -- briefly say so and redirect toward what K9-AIF "
    "topics you can actually help with."
)


class ChatAgent(BaseAgent):

    def __init__(self, config=None):
        if config is None:
            config = load_yaml(os.path.join(BASE_DIR, "config.yaml"))

        super().__init__(config)

        self.router = ModelRouterFactory.get_router(config)
        self._cache = CacheFactory.create(config)
        self.guard_agent = GuardAgent(config)

        chat_cfg = config.get("chat", {})
        self._session_ttl = int(chat_cfg.get("session_ttl_seconds", 3600))
        self._max_history = int(chat_cfg.get("max_history", 20))

    # ------------------------------------------------------------------
    # Session history — get/append/format
    # ------------------------------------------------------------------
    def _history_key(self, session_id: str) -> str:
        return f"k9chat:history:{session_id}"

    def _get_history(self, session_id: str) -> list:
        raw = self._cache.get(self._history_key(session_id))
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_history(self, session_id: str, history: list) -> None:
        if len(history) > self._max_history:
            history = history[-self._max_history:]
        self._cache.set(
            self._history_key(session_id),
            json.dumps(history),
            ttl=self._session_ttl,
        )

    def clear_history(self, session_id: str) -> None:
        self._cache.delete(self._history_key(session_id))

    def truncate_history(self, session_id: str, keep_count: int) -> None:
        """Drops every turn from keep_count onward -- the server-side half
        of "edit a message and resubmit." Editing a message has to forget
        everything after it on both sides (the visible transcript AND the
        model's own memory of the conversation), or the model would still
        answer as if the turns you just erased actually happened."""
        history = self._get_history(session_id)
        self._save_history(session_id, history[:max(0, keep_count)])

    def _format_prompt(
        self,
        history: list,
        new_message: str,
        project_instructions: str = "",
        project_context: list | None = None,
        knowledge_context: list | None = None,
        web_context: list | None = None,
        unhinged_level: int = 0,
        profanity_level: int = 0,
        length_level: int = 1,
    ) -> str:
        """Render project instructions/context + prior turns + the new
        message into a single prompt string.

        Project context and knowledge-base context are always
        supplementary, never a replacement for conversation history --
        same principle as dow-k9-aif's ViewGeneratorAgent fix earlier
        tonight: the thing the user is actually asking about (their own
        conversation) must never be displaced by retrieved reference
        material, and the model is told explicitly not to confuse the two.

        Kept as two separate labeled blocks rather than merged into one --
        conflating "this project's uploaded files" with "the K9-AIF/K9X
        documentation corpus" would misattribute retrieved content to the
        wrong source.
        """
        lines = [SCOPE_INSTRUCTION, ""]
        unhinged_instruction = UNHINGED_INSTRUCTIONS.get(unhinged_level, "")
        if unhinged_instruction:
            lines.append(unhinged_instruction)
        profanity_instruction = PROFANITY_INSTRUCTIONS.get(profanity_level, "")
        if profanity_instruction:
            lines.append(profanity_instruction)
        length_instruction = LENGTH_INSTRUCTIONS.get(length_level, "")
        if length_instruction:
            lines.append(length_instruction)
        if unhinged_instruction or profanity_instruction or length_instruction:
            lines.append("")

        if project_instructions:
            lines.append(f"Project instructions: {project_instructions}")
            lines.append("")

        if knowledge_context:
            lines.append(
                "Reference material from the K9-AIF Framework and K9X "
                "ecosystem documentation (supplementary -- use only if "
                "relevant to the question; the conversation below is what "
                "the user is actually asking about):"
            )
            for chunk in knowledge_context:
                lines.append(f"- {chunk['text']}")
            lines.append("")

        if project_context:
            lines.append(
                "Reference material from this project's uploaded files "
                "(supplementary -- use only if relevant to the question; "
                "the conversation below is what the user is actually "
                "asking about):"
            )
            for chunk in project_context:
                lines.append(f"- {chunk['text']}")
            lines.append("")

        if web_context:
            lines.append(
                "Live web search results for the user's question (real, "
                "current, fetched just now -- not from training data). "
                "The scope instruction above about declining unrelated "
                "code/image requests does NOT apply here: answering a "
                "general question using these live results is a real, "
                "intended K9Chat capability when Internet search is "
                "enabled, not an off-scope request. Use these results "
                "directly if they answer the question; say so plainly if "
                "they don't."
            )
            for r in web_context:
                lines.append(f"- {r['title']}: {r['content']} ({r['url']})")
            lines.append("")

        for turn in history:
            role = "User" if turn["role"] == "user" else "Assistant"
            lines.append(f"{role}: {turn['content']}")
        lines.append(f"User: {new_message}")
        lines.append("Assistant:")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Execute — full response (synchronous)
    # ------------------------------------------------------------------
    def execute(self, request):
        message = request.get("text") or request.get("prompt", "")
        session_id = request.get("session_id", "default")
        project_instructions = request.get("project_instructions", "")
        project_context = request.get("project_context")
        knowledge_context = request.get("knowledge_context")
        web_context = request.get("web_context")
        unhinged_level = request.get("unhinged_level", 0)
        profanity_level = request.get("profanity_level", 0)
        length_level = request.get("length_level", 1)

        guard_result = self.guard_agent.execute({"text": message})
        if not guard_result["passed"]:
            reply = self.guard_agent.refusal_message
            history = self._get_history(session_id)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            self._save_history(session_id, history)
            return {"text": reply, "model": None, "session_id": session_id, "blocked": True}

        history = self._get_history(session_id)
        prompt = self._format_prompt(
            history, message, project_instructions, project_context, knowledge_context,
            web_context, unhinged_level, profanity_level, length_level,
        )

        inf_req = InferenceRequest(prompt=prompt, task_type="chat")
        response = self.router.invoke(inf_req)

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response.output})
        self._save_history(session_id, history)

        return {
            "text": response.output,
            "model": response.model_alias,
            "session_id": session_id,
        }

    # ------------------------------------------------------------------
    # Execute — streaming
    # ------------------------------------------------------------------
    async def execute_stream(self, request):
        """
        Stream the chat response incrementally. Mirrors ``execute()`` but
        yields text chunks as they arrive from the LLM instead of returning
        a complete dict. Used when ``chat.stream: true`` in config.

        Conversation history is retrieved and persisted the same way as
        ``execute()`` — multi-turn context works identically whether
        streaming is on or off.
        """
        message = request.get("text") or request.get("prompt", "")
        session_id = request.get("session_id", "default")
        project_instructions = request.get("project_instructions", "")
        project_context = request.get("project_context")
        knowledge_context = request.get("knowledge_context")
        web_context = request.get("web_context")
        unhinged_level = request.get("unhinged_level", 0)
        profanity_level = request.get("profanity_level", 0)
        length_level = request.get("length_level", 1)

        guard_result = self.guard_agent.execute({"text": message})
        if not guard_result["passed"]:
            reply = self.guard_agent.refusal_message
            yield reply
            history = self._get_history(session_id)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            self._save_history(session_id, history)
            return

        history = self._get_history(session_id)
        prompt = self._format_prompt(
            history, message, project_instructions, project_context, knowledge_context,
            web_context, unhinged_level, profanity_level, length_level,
        )

        inf_req = InferenceRequest(prompt=prompt, task_type="chat")

        full_response = []
        async for chunk in llm_invoke_stream(self.config, inf_req):
            full_response.append(chunk)
            yield chunk

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": "".join(full_response)})
        self._save_history(session_id, history)