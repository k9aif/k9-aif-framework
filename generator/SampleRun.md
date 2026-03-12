# K9-AIF Generator – Sample Run

This document shows an example run of the **K9-AIF application generator**.

The generator scaffolds a new application by creating a standard
project structure including agents, orchestrators, configuration,
and test files.

---

## Generator CLI

``` bash

$ ./k9_generator.sh

=== K9-AIF Generator v0.1.0 ===

K9-AIF Generator CLI

Usage:
  ./k9_generator.sh preview <AppName>
  ./k9_generator.sh run <AppName>
  ./k9_generator.sh recycle <AppName>

Examples:
  ./k9_generator.sh preview WeatherAssist
  ./k9_generator.sh run ACMEInsurance
  ./k9_generator.sh recycle PetStore
```
---
## Preview Mode

``` bash
$ ./k9_generator.sh preview projectX

=== K9-AIF Generator v0.1.0 ===

Preview of files that will be generated for projectX

[PREVIEW] Application: projectX
[PREVIEW] Target folder: ./k9_projects/project_x

[PREVIEW] Will create:

k9_projects/project_x/
  agents/
  orchestrators/
  config/
  main.py
  tests/test_project_x.py
  agents/retrieval_agent.py
  agents/enrichment_agent.py
  agents/summarizer_agent.py
  orchestrators/default_flow_orchestrator.py
  config/config.yaml
  config/flows.yaml

--- Done! ---
```

## Run Mode

``` bash

(k9_aif_venv) ravinatarajan@Ravis-MacBook-Pro K9-AIF % ./k9_generator.sh run projectX

=== K9-AIF Generator v0.1.0 ===

[INFO] Working...
[INFO] Creating folder: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/agents
[INFO] Creating folder: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/orchestrators
[INFO] Creating folder: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/config
[INFO] Creating folder: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/tests
[INFO] Generating agents...
[INFO] Writing file: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/agents/retrieval_agent.py
[INFO] Writing file: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/agents/enrichment_agent.py
[INFO] Writing file: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/agents/summarizer_agent.py
[INFO] Generating orchestrator...
[INFO] Writing file: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/orchestrators/default_flow_orchestrator.py
[INFO] Generating config.yaml and flows.yaml...
[INFO] Generating main.py...
[INFO] Generating tests/test_project_x.py...
[INFO] Generating tests/conftest.py...
[INFO] Writing file: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/__init__.py
[INFO] Writing file: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/agents/__init__.py
[INFO] Writing file: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/orchestrators/__init__.py
[INFO] Writing file: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/config/__init__.py
[INFO] Writing file: /Users/ravinatarajan/K9-AIF/k9_projects/project_x/tests/__init__.py

[INFO] Generated file tree:
project_x/
  __init__.py
  main.py
  config/
    config.yaml
    __init__.py
    flows.yaml
  tests/
    conftest.py
    test_project_x.py
    __init__.py
  agents/
    enrichment_agent.py
    summarizer_agent.py
    retrieval_agent.py
    __init__.py
  orchestrators/
    default_flow_orchestrator.py
    __init__.py

[K9-AIF] Application projectX generated successfully!

Ready to Rumble!
(k9_aif_venv) ravinatarajan@Ravis-MacBook-Pro K9-AIF %

```
