
# K9-AIF Project Generator

The **K9-AIF Generator** bootstraps new projects that follow the architecture and conventions of the **K9 Agentic Integration Framework (K9-AIF)**.

It creates a ready-to-run project structure including:

- Agents
- Orchestrator
- Flow definitions
- Configuration files
- Entry point (`main.py`)
- Test scaffolding

The generator uses **Jinja2 templates** to produce consistent project layouts for K9-AIF based applications.

---

Note: checkout the SampleRun.md 

---

## Directory Structure
``` bash
k9_aif_generator/
│
├── generator.py
├── templates/
│   ├── agent_template.py.j2
│   ├── orchestrator_template.py.j2
│   ├── main_template.py.j2
│   ├── config_template.yaml.j2
│   ├── flows_template.yaml.j2
│   ├── contest_template.py.j2
│   └── test_template.py.j2
```

## Generate stubs for new project

Example: ./k9_generator.sh run my_project

This will generate a new directory:

``` bash
my_project/

agents/
orchestrator/
config/
flows/
tests/
main.py

```

The generated project follows the **K9-AIF architecture layers**:

``` text
- Application Layer
- Orchestration Layer
- Agent Layer
- Integration Layer
- Security & Governance

```

---

## Templates

All project files are generated from templates located in: templates/

These templates use **Jinja2** and can be customized to extend the project structure.

---

## Purpose

The generator ensures that all new projects created with **K9-AIF** follow a consistent structure and architectural pattern, making it easier to build governed enterprise multi-agent systems.

---

## Related

K9-AIF Framework

https://k9aif.com

GitHub Repository

https://github.com/k9aif/k9-aif-framework
