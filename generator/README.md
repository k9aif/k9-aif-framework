# K9-AIF Project Stub Generator

The K9-AIF Generator bootstraps new applications that follow the architecture and conventions of the K9 Agentic Integration Framework (K9-AIF).

It creates a ready-to-run application scaffold including:

-	Agents
-	Orchestrator
-	Squad configuration
-	Agent configuration
-	Application configuration
-	Entry point (main.py)
-	Test scaffolding

The generator uses Jinja2 templates to produce consistent project layouts for K9-AIF based applications.

---

## Quick Start (Step by Step)

From the root of the K9-AIF framework repository:

``` code
k9-aif-framework/

```

1. Preview what will be generated
   
``` bash
./k9_generator.sh preview MyApp

```
This shows the directory structure without creating files.

2. Generate the App

``` bash
./k9_generator.sh run MyApp

```
The generator will create:

``` code
k9_projects/MyApp

```

3. Change into the generated app folder

``` bash
cd k9_projects/MyApp

```

4. Run the Application

``` bash
python main.py
```

You should see output similar to:

``` code
Executing MyApp with request: {'query': 'hello'}

Hello World from K9-AIF Application Stub
```
This confirms the generated K9-AIF application scaffold is working.

5. Run tests

The generator also creates a test scaffold.

``` bash
pytest
```

Expected output:

``` code
[K9-AIF] Testing generated code...

[K9-AIF] All tests passed!
```
---

## Generated App Structure

``` code

k9_projects/MyApp/

MyApp/
│
├── agents/
│   ├── retrieval_agent.py
│   ├── enrichment_agent.py
│   └── summarizer_agent.py
│
├── orchestrators/
│   └── default_orchestrator.py
│
├── config/
│   ├── config.yaml
│   ├── squads.yaml
│   └── agents.yaml
│
├── tests/
│   ├── test_MyApp.py
│   └── conftest.py
│
└── main.py
```

---

## Developer Guide

For a deeper explanation of the K9-AIF architecture and how to extend generated applications, please refer to the developer guide:

`docs/Developer-guide-readme.md`

This document explains:

- K9-AIF architectural layers
- Squad and Agent design
- Orchestrator responsibilities
- Configuration structure
- How to extend generated projects with real domain logic

## Need Help?

If you encounter issues running the generator, please contact:

ravinatarajan@k9aif.com

