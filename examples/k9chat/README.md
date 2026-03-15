K9Chat Example

This example demonstrates a minimal chat application built on the K9-AIF framework, showcasing:

- ABB / SBB architecture
- Squad and Agent structure
- Model routing via K9ModelRouter
- Integration with LLMs (Ollama / configured provider)

Contents

- chat.py — Entry point to run K9Chat in interactive mode.
- chat_agent.py — Agent implementation handling chat prompts.
- chat_squad.py — Defines the squad containing the chat agent.
- config.yaml — Minimal configuration for LLM provider and routing.
- squad.yaml — Squad definition for k9chat.

Requirements
- Python 3.13+
- Virtual environment with K9-AIF dependencies installed

Running K9Chat

From the root of the k9-aif-framework repo:

``` bash
cd examples/k9chat
python chat.py

> who is Elon Musk?
Elon Musk is a South African-born entrepreneur, inventor, and business magnate...

>
```
