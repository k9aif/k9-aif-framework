from __future__ import annotations

from typing import Any, Dict, Optional, TypedDict

from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from .tools import get_weather_for_city


class WeatherState(TypedDict):
    weather_facts: str
    output: str


def _build_llm(config: Optional[Dict[str, Any]] = None) -> ChatOllama:
    """
    Same config-resolution discipline as weather_assist/crewai/crew.py's
    _build_llm(): read the already-resolved config.yaml (ollama.base_url/
    model) rather than a second, independent os.getenv() lookup. No
    hardcoded host default -- config.yaml's own
    ${OLLAMA_BASE_URL:-http://localhost:11434} is the single place that
    default lives.

    Unlike CrewAI's LLM class, ChatOllama has no base_url/api_base split
    to get wrong -- langchain_ollama.ChatOllama passes base_url straight
    to the ollama Python client, which is the only HTTP client in this
    call path. Confirmed directly (constructed a ChatOllama and inspected
    the call failing against the *configured* host, not a hardcoded one),
    not assumed from either library's docs -- the CrewAI adapter's
    api_base bug is exactly why this needed checking rather than assuming
    the same shape applies here.
    """
    ollama_cfg = (config or {}).get("ollama", {})
    model = ollama_cfg.get("model", "llama3.2:1b")
    base_url = ollama_cfg.get("base_url", "http://localhost:11434")
    return ChatOllama(model=model, base_url=base_url)


def _fetch_weather_node_factory(city: str):
    """
    Deterministic tool call, not an LLM-mediated one -- mirrors CrewAI's
    Weather Agent, whose own task instructions demand it return only the
    tool's exact output with no added commentary. Making that determinism
    structural here (a plain function call, not a model deciding whether
    and how to call the tool) is a stronger version of the same intent,
    not a different design: LangGraph's graph model makes "this step is
    deterministic" an architectural fact instead of a prompted-for one.

    city is closed over at graph-build time, not read from invoke()'s
    input state -- the same choice weather_assist/crewai/crew.py makes,
    baking city into each task's description string when the Crew is
    built rather than expecting it to survive K9CrewAIAdapter's generic
    payload normalization at runtime. The K9-AIF envelope
    (message/intent/context/metadata) that actually reaches invoke() is
    a different shape than this graph's own state schema, and forcing
    them to match would leak K9-AIF's generic envelope into
    domain-specific graph state.
    """

    def _fetch_weather_node(state: WeatherState) -> Dict[str, Any]:
        weather_facts = get_weather_for_city(city)
        return {"weather_facts": weather_facts}

    return _fetch_weather_node


def _summarize_weather_node_factory(config: Optional[Dict[str, Any]] = None):
    llm = _build_llm(config)

    def _summarize_weather_node(state: WeatherState) -> Dict[str, Any]:
        prompt = (
            "Using only the factual weather findings below, write a concise "
            "weather summary for the user. Include current conditions, "
            "today's high/low, precipitation chance, and one practical "
            "suggestion. Keep it under 120 words. Do not mention limitations. "
            "Do not mention APIs. Do not provide code.\n\n"
            f"Factual weather findings:\n{state['weather_facts']}"
        )
        response = llm.invoke(prompt)
        return {"output": response.content}

    return _summarize_weather_node


def build_weather_assist_graph(city: str, config: Optional[Dict[str, Any]] = None):
    """
    Two-node graph mirroring weather_assist/crewai/crew.py's two-agent
    Crew exactly: fetch (tool call) -> summarize (LLM call). Same
    division of responsibility, same prompt content, different execution
    model -- CrewAI's sequential Process vs. LangGraph's explicit node/
    edge graph.
    """
    graph = StateGraph(WeatherState)
    graph.add_node("fetch_weather", _fetch_weather_node_factory(city))
    graph.add_node("summarize_weather", _summarize_weather_node_factory(config))
    graph.set_entry_point("fetch_weather")
    graph.add_edge("fetch_weather", "summarize_weather")
    graph.add_edge("summarize_weather", END)
    return graph.compile()
