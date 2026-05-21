#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — Live LLM Call Monitor
#
# Usage:
#   python watch_llm.py                     # default http://localhost:8000
#   python watch_llm.py http://host:8000

import json
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("pip install rich")
    sys.exit(1)

EOC_URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
SSE_URL = f"{EOC_URL}/events/stream"

MAX_ROWS = 30

TASK_COLOURS = {
    "fraud":        "red",
    "adjudication": "magenta",
    "guardrails":   "yellow",
    "extraction":   "blue",
    "general":      "cyan",
    "audit_report": "green",
    "customer_intent": "cyan",
    "summarization":   "cyan",
}

MODEL_COLOURS = {
    "reasoning":  "magenta",
    "guardian":   "yellow",
    "extraction": "blue",
    "general":    "cyan",
}


def _colour_task(task: str) -> Text:
    colour = TASK_COLOURS.get(task, "white")
    return Text(task, style=colour)


def _colour_model(model: str, alias: str) -> Text:
    colour = MODEL_COLOURS.get(alias, "white")
    return Text(model, style=colour)


def _tok(n) -> str:
    return str(n) if n is not None else "–"


def build_table(calls: list) -> Table:
    t = Table(
        title=f"[bold]Live LLM Calls[/bold]  [dim]{EOC_URL}[/dim]",
        expand=True,
        show_lines=False,
        border_style="dim",
    )
    t.add_column("#",        style="dim",    width=4,  no_wrap=True)
    t.add_column("Time",                     width=10, no_wrap=True)
    t.add_column("Agent",    style="cyan",   width=26, no_wrap=True)
    t.add_column("Task",                     width=18, no_wrap=True)
    t.add_column("Model",                    width=26, no_wrap=True)
    t.add_column("Latency",  justify="right",width=10, no_wrap=True)
    t.add_column("In",       justify="right",width=7,  no_wrap=True)
    t.add_column("Out",      justify="right",width=7,  no_wrap=True)

    visible = calls[-MAX_ROWS:]
    for i, c in enumerate(visible, 1):
        lat = c.get("latency_ms")
        lat_str = f"{lat} ms" if lat else "?"
        lat_style = "red" if (lat or 0) > 5000 else ("yellow" if (lat or 0) > 2000 else "green")
        t.add_row(
            str(len(calls) - len(visible) + i),
            c["time"],
            c["agent"],
            _colour_task(c["task_type"]),
            _colour_model(c["model"], c.get("alias", "")),
            Text(lat_str, style=lat_style),
            _tok(c.get("tokens_in")),
            _tok(c.get("tokens_out")),
        )
    if not calls:
        t.add_row("–", "–", "waiting for LLM calls…", "–", "–", "–", "–", "–")
    return t


def main():
    calls = []
    console = Console()
    console.print(f"[dim]Connecting to SSE stream → {SSE_URL}[/dim]")
    console.print("[dim]Press Ctrl-C to exit[/dim]\n")

    with Live(build_table(calls), refresh_per_second=4, console=console) as live:
        try:
            with requests.get(SSE_URL, stream=True, timeout=None) as r:
                r.raise_for_status()
                for raw_line in r.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if evt.get("type") != "LLMCall":
                        continue
                    calls.append({
                        "time":       datetime.now().strftime("%H:%M:%S"),
                        "agent":      evt.get("agent", "?"),
                        "task_type":  evt.get("task_type", "?"),
                        "model":      evt.get("model", "?"),
                        "alias":      evt.get("model", "?").split(":")[0],
                        "latency_ms": evt.get("latency_ms"),
                        "tokens_in":  evt.get("tokens_in"),
                        "tokens_out": evt.get("tokens_out"),
                    })
                    live.update(build_table(calls))
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            console.print(f"\n[red]Stream error:[/red] {exc}")


if __name__ == "__main__":
    main()
