# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""DoclingParser against Docling-Serve's /v1/convert/file contract.

Before 1.15.2 the constructor passed ``name=`` to BaseAgent (TypeError on 1.15)
and the framework config defaulted to ``/v1/parse``, which Docling-Serve does not
serve. Set DOCLING_ENDPOINT to also run the live conversion test."""

import os

import httpx
import pytest

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_agents.retrieval.docling_parser import DEFAULT_URL, DocumentConversionError, DoclingParser


def _server(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return httpx.Response(200, json={
            "status": "success",
            "document": {"filename": "x.pdf", "md_content": "# Title\n\nBody text."},
            "errors": [],
        })
    return httpx.MockTransport(handler)


def test_constructs_on_current_base_agent():
    p = DoclingParser()
    assert p.url == DEFAULT_URL
    assert p.url.endswith("/v1/convert/file")


def test_endpoint_from_external_services(monkeypatch):
    monkeypatch.setenv("DOCLING_ENDPOINT", "http://docling.test:5001/v1/convert/file")
    cfg = {"external_services": {"docling": {"endpoint": "${DOCLING_ENDPOINT:-http://localhost:5001/v1/convert/file}"}}}
    assert DoclingParser(config=cfg).url == "http://docling.test:5001/v1/convert/file"


def test_endpoint_from_retrieval_host():
    cfg = {"retrieval": {"docling": {"host": "http://docling.test:5001/"}}}
    assert DoclingParser(config=cfg).url == "http://docling.test:5001/v1/convert/file"


def test_framework_config_default_is_convert_file():
    from k9_aif_abb.k9_utils.config_loader import load_yaml
    from pathlib import Path
    import k9_aif_abb
    cfg = load_yaml(Path(k9_aif_abb.__file__).parent / "config" / "config.yaml")
    assert cfg["external_services"]["docling"]["endpoint"].endswith("/v1/convert/file")


def test_execute_posts_file_with_ocr_and_returns_markdown(tmp_path):
    seen = {}
    f = tmp_path / "req.docx"
    f.write_bytes(b"PK\x03\x04 fake docx")
    p = DoclingParser(transport=_server(seen))
    out = p.execute({"path": str(f)})
    assert out["status"] == "ok" and out["filename"] == "req.docx"
    assert out["markdown"].startswith("# Title")
    assert "data" not in out
    assert seen["url"] == DEFAULT_URL
    body = seen["body"]
    assert b'name="to_formats"' in body and b"md" in body
    assert b'name="do_ocr"' in body and b"true" in body
    assert b"wordprocessingml" in body  # MIME from the suffix, not always PDF


def test_http_error_raises_from_execute_and_is_reported_by_convert(tmp_path):
    """As an agent, a failed conversion propagates (1.19.0); convert() still reports it as a result."""
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    p = DoclingParser(transport=httpx.MockTransport(lambda r: httpx.Response(404, text="Not Found")))
    with pytest.raises(DocumentConversionError) as exc:
        p.execute({"path": str(f)})
    assert exc.value.result["status"] == "error" and "404" in exc.value.result["error"]
    assert p.convert("a.pdf", b"%PDF")["status"] == "error"


def test_empty_conversion_is_an_error(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    empty = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "success", "document": {"md_content": ""}}))
    with pytest.raises(DocumentConversionError):
        DoclingParser(transport=empty).execute({"path": str(f)})


def test_missing_file_is_an_error():
    with pytest.raises(DocumentConversionError) as exc:
        DoclingParser().execute({"path": "/no/such/file.pdf"})
    assert "File not found" in exc.value.result["error"]


def test_failed_conversion_stops_the_squad(tmp_path):
    """Inside a squad flow the next agent never runs on an empty document."""
    from k9_aif_abb.k9_squad.base_squad import BaseSquad
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    ran = []

    class SummaryAgent(BaseAgent):
        def execute(self, payload):
            ran.append(payload)
            return {"output": "summary"}

    parser = DoclingParser(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    squad = BaseSquad("docs", [parser, SummaryAgent(config={})])
    squad.flow = [{"agent": "DoclingParser", "result_key": "doc"}, {"agent": "SummaryAgent", "result_key": "summary"}]
    with pytest.raises(DocumentConversionError):
        squad.execute({"path": str(f)})
    assert ran == []


def test_governed_by_shield_on_a_large_file(tmp_path, monkeypatch):
    """Shield checks the payload (a path), not the document's bytes."""
    from k9_aif_abb.k9_utils.config_loader import load_yaml
    from pathlib import Path
    import k9_aif_abb
    monkeypatch.setenv("K9_ENV", "production")
    cfg = load_yaml(Path(k9_aif_abb.__file__).parent / "config" / "config.yaml")
    cfg["security"]["shield"]["enabled"] = True
    f = tmp_path / "big.pdf"
    f.write_bytes(b"%PDF" + b"x" * 500_000)
    p = DoclingParser(config=cfg, transport=_server({}))
    assert type(p.governance).__name__ == "ShieldGovernance"
    assert p.execute({"path": str(f)})["status"] == "ok"


@pytest.mark.skipif(not os.environ.get("DOCLING_ENDPOINT"), reason="DOCLING_ENDPOINT not set")
def test_live_docx_conversion(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Capability Requirement", 1)
    d.add_paragraph("The system shall detect small UAS at 5 km.")
    f = tmp_path / "req.docx"
    d.save(str(f))
    out = DoclingParser(url=os.environ["DOCLING_ENDPOINT"]).execute({"path": str(f)})
    assert out["status"] == "ok", out
    assert "5 km" in out["markdown"]
