## Preview & Run (generate) the files to be generated

```bash

(.venv) ravinatarajan@Ravis-MacBook-Pro k9-aif-framework % ./k9_generator.sh preview my_app

=== K9-AIF Generator v0.1.0 ===

Preview of files that will be generated for my_app

[PREVIEW] Application: my_app
[PREVIEW] Target folder: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app
[PREVIEW] Will create:
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/agents/
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/squads/
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/orchestrators/
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/config/
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/tests/
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/main.py
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/agents/retrieval_agent.py
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/agents/enrichment_agent.py
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/agents/summarizer_agent.py
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/squads/default_squad.py
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/orchestrators/default_orchestrator.py
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/config/config.yaml
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/config/squads.yaml
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/config/agents.yaml
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/tests/test_my_app.py
  /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/tests/conftest.py

 --- Done! ---
(.venv) ravinatarajan@Ravis-MacBook-Pro k9-aif-framework % ./k9_generator.sh run my_app    

=== K9-AIF Generator v0.1.0 ===

[INFO] Working...
[INFO] Creating folder: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/agents
[INFO] Creating folder: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/squads
[INFO] Creating folder: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/orchestrators
[INFO] Creating folder: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/config
[INFO] Creating folder: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/tests
[INFO] Generating agents...
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/agents/retrieval_agent.py
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/agents/enrichment_agent.py
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/agents/summarizer_agent.py
[INFO] Generating squad...
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/squads/default_squad.py
[INFO] Generating orchestrator...
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/orchestrators/default_orchestrator.py
[INFO] Generating config.yaml, squads.yaml, and agents.yaml...
[INFO] Generating main.py...
[INFO] Generating tests/test_my_app.py...
[INFO] Generating tests/conftest.py...
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/__init__.py
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/agents/__init__.py
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/squads/__init__.py
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/orchestrators/__init__.py
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/config/__init__.py
[INFO] Writing file: /Users/ravinatarajan/ai/k9-aif-framework/k9_projects/my_app/tests/__init__.py

[INFO] Generated file tree:
my_app/
  __init__.py
  main.py
  agents/
    __init__.py
    enrichment_agent.py
    retrieval_agent.py
    summarizer_agent.py
  config/
    __init__.py
    agents.yaml
    config.yaml
    squads.yaml
  orchestrators/
    __init__.py
    default_orchestrator.py
  squads/
    __init__.py
    default_squad.py
  tests/
    __init__.py
    conftest.py
    test_my_app.py

[K9-AIF] Application my_app generated successfully!

Next steps:
cd k9_projects/my_app
python main.py

Ready to Rumble!
(.venv) ravinatarajan@Ravis-MacBook-Pro k9-aif-framework % 

```

---

## Run the Application generated

```bash

(.venv) ravinatarajan@Ravis-MacBook-Pro k9-aif-framework % cd k9_projects/my_app  
(.venv) ravinatarajan@Ravis-MacBook-Pro my_app % python main.py

==================================
🐾 K9-AIF Application Starting
==================================

Loading squad: my_app_squad
Initializing orchestrator
Executing agents...

----------------------------------
Hello World from K9-AIF Application Stub
----------------------------------

Ready to Rumble!

You are now ready to customize your application by adding components.
Refer to the User Guide in the docs folder for next steps.

(.venv) ravinatarajan@Ravis-MacBook-Pro my_app %

```

## Run PyTest 

```bash

(.venv) ravinatarajan@Ravis-MacBook-Pro k9-aif-framework % pytest k9_projects/my_app/tests

[K9-AIF] Running tests for generated application scaffold...

====================================================== test session starts =======================================================
platform darwin -- Python 3.11.14, pytest-8.3.3, pluggy-1.5.0
rootdir: /Users/ravinatarajan/ai/k9-aif-framework
plugins: docker-3.1.2, anyio-4.9.0, langsmith-0.3.45
collected 2 items                                                                                                                

k9_projects/my_app/tests/test_my_app.py ..                                                                                 [100%]Woof!

   / \__
  ( ^   @\___
  /         O
 /   (_____/
/_____/   U

[K9-AIF] 
[K9-AIF] All tests passed! completed successfully!
[READY TO RUMBLE!] 

[K9-AIF] The generated application scaffold is working correctly.
         You are now ready to customize your application by
         adding agents, orchestrators, and domain components.
         Refer to the User Guide in the docs folder.

Ready to Rumble!



======================================================= 2 passed in 0.03s ========================================================
(.venv) ravinatarajan@Ravis-MacBook-Pro k9-aif-framework % 

```

you can run the pytest command from main folder or within the my_app folder. either way it will work.

Enjoy! 

```code
if you need help or does not work for you,  contact: ravinatarajan@k9x.ai

```

