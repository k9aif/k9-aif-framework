# Getting Started with K9-AIF

**5 steps from zero to a running governed multi-agent system.**

Prerequisites: Python 3.11+, Git, Ollama running locally or at a reachable host.

---

## Step 1 — Create a project and install the framework

```bash
mkdir my-k9-solution
cd my-k9-solution
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install git+https://github.com/k9aif/k9-aif-framework.git
```

Verify:
```bash
python3 -c "import k9_aif_abb; print('K9-AIF ready')"
```

---

## Step 2 — Configure your LLM

Create `config.yaml` in your project folder:

```yaml
inference:
  router:
    type: k9_model_router
    default_model: general
    persistence:
      enabled: true
      provider: sqlite
      sqlite:
        db_path: "./runtime/k9_model_router.db"

  llm_factory:
    base_url: "http://localhost:11434"   # your Ollama host
    models:
      general: "llama3.2:1b"
      reasoning: "llama3.2:1b"

  models:
    general:
      provider: ollama
      llm_ref: general
      capabilities: [general, chat, summarization]
    reasoning:
      provider: ollama
      llm_ref: reasoning
      capabilities: [reasoning, analysis]
```

---

## Step 3 — Write your first agent

Create `my_agent.py`:

```python
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke
import yaml

class HelloAgent(BaseAgent):
    layer = "HelloAgent SBB"

    def execute(self, payload):
        config = self.config
        req = InferenceRequest(
            prompt=f"Say hello to: {payload.get('name', 'World')}",
            task_type="general",
        )
        resp = llm_invoke(config, req)
        return {"agent": "HelloAgent", "output": resp.output, "model": resp.model_alias}


# Load config and run
with open("config.yaml") as f:
    config = yaml.safe_load(f)

agent = HelloAgent(config=config)
result = agent.execute({"name": "K9-AIF"})
print(result)
```

Run it:
```bash
python3 my_agent.py
```

---

## Step 4 — Run the framework tests (no LLM needed)

```bash
pip install pytest
cd .venv/lib/python3.11/site-packages/k9_aif_abb/tests/
pytest test_framework.py -v
pytest test_intelligent_model_router.py -v
```

All tests pass with no external services. The model router, agent registry, squad loader, and governance pipeline are all tested offline.

---

## Step 5 — Run the ACME Support Center example

The ACME Support Center is a minimal working multi-agent system included in the framework:

```bash
# Clone the framework to access the examples
git clone https://github.com/k9aif/k9-aif-framework.git
cd k9-aif-framework
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the example (needs Ollama)
./run_acme_support_center.sh
```

This runs: Router → Orchestrator → Squad → 3 Agents → LLM → result.
Every routing decision is persisted to SQLite at `runtime/k9_model_router.db`.

---

## What you now have

After Step 1–3 you have:
- A governed agent that routes through K9ModelRouter
- Every LLM call scored by task_type, cost, and latency
- Routing decisions persisted to SQLite with full audit trail

After Step 4–5 you have verified:
- Framework contracts work (tests)
- A complete multi-agent pipeline runs end-to-end (ACME example)

---

## Next steps

- Add a Squad: [SKILLS.md — Skill 4](../SKILLS.md)
- Add governance enforcement: [SKILLS.md — Skill 5](../SKILLS.md)
- Use with CrewAI: install `crewai` and use `K9XLiteLLMBridgeAdapter`
- Deploy the full EOC reference: `examples/K9X_Enterprise_Insurance_OperationsCenter/`
