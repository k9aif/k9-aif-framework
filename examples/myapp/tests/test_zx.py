from unittest.mock import patch, MagicMock
from examples.myapp.agents.src.zx import Zx
from k9_aif_abb.k9_inference.models.inference_response import InferenceResponse


class _TestGovernance:
    def pre_process(self, payload, ctx=None): return payload
    def post_process(self, payload, ctx=None): return payload


def test_execute_returns_output():
    mock_resp = MagicMock(spec=InferenceResponse)
    mock_resp.output = "Result."
    mock_resp.model_alias = "reasoning"
    mock_resp.provider = "ollama"

    with patch("examples.myapp.agents.src.zx.llm_invoke", return_value=mock_resp):
        agent = Zx(config={}, governance=_TestGovernance())
        result = agent.execute({"input": "test"})

    assert result["agent"] == "Zx"
    assert "output" in result


def test_execute_handles_llm_unavailable():
    with patch("examples.myapp.agents.src.zx.llm_invoke",
               side_effect=RuntimeError("LLM backend unavailable")):
        agent = Zx(config={}, governance=_TestGovernance())
        result = agent.execute({"input": "test"})

    assert "[WARN]" in result["output"]
    assert result["confidence"] == 0.0
