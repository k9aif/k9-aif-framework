from __future__ import annotations

import os

from crewai import Agent, Crew, Process, Task, LLM

from .tools import get_weather_for_city


def _build_llm() -> LLM:
    model = os.getenv("OLLAMA_MODEL", "ollama/llama3.2:1b")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.98:11434")
    return LLM(model=model, base_url=base_url)


def build_weather_assist_crew(city: str) -> Crew:
    llm = _build_llm()

    weather_agent = Agent(
        role="Weather Agent",
        goal=f"Gather accurate weather facts for {city} using the provided tool.",
        backstory=(
            "You are a precise weather researcher. "
            "You must use the weather tool and return only the tool results. "
            "Do not add commentary, code, or external suggestions."
        ),
        tools=[get_weather_for_city],
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    summary_agent = Agent(
        role="Weather Summary Agent",
        goal="Turn provided weather facts into a concise user-facing summary.",
        backstory=(
            "You are a concise weather communicator. "
            "You only summarize the factual weather report provided to you. "
            "Do not say you lack real-time access. Do not suggest external APIs."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    weather_task = Task(
        description=(
            f"Use the tool get_weather_for_city for '{city}'. "
            "Return only the exact factual weather findings from the tool. "
            "Do not add explanations, code, thoughts, or recommendations."
        ),
        expected_output=(
            "A plain factual weather report containing current conditions, temperature, "
            "high/low, precipitation probability, and wind."
        ),
        agent=weather_agent,
    )

    summary_task = Task(
        description=(
            "Using only the factual weather findings from the previous task, "
            "write a concise weather summary for the user. "
            "Include current conditions, today's high/low, precipitation chance, "
            "and one practical suggestion. "
            "Keep it under 120 words. "
            "Do not mention limitations. "
            "Do not mention APIs. "
            "Do not provide code."
        ),
        expected_output="A concise plain-English weather summary.",
        agent=summary_agent,
        context=[weather_task],
    )

    return Crew(
        agents=[weather_agent, summary_agent],
        tasks=[weather_task, summary_task],
        process=Process.sequential,
        verbose=True,
    )