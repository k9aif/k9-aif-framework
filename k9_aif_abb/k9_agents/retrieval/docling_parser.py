# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_agents/retrieval/docling_parser.py

import asyncio
import mimetypes
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_utils.config_loader import _expand

DEFAULT_URL = "http://localhost:5001/v1/convert/file"

_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".md": "text/markdown",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _mime(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return _MIME.get(suffix) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


class DoclingParser(BaseAgent):
    """
    DoclingParser - Retrieval ABB
    -----------------------------
    Install: ``pip install "k9-aif[docling]"`` (adds httpx).

    Converts PDF, Word, PowerPoint, Excel, HTML and image files to Markdown through a
    Docling-Serve instance (``POST /v1/convert/file``), with layout analysis and OCR
    for scanned pages.

    Endpoint, first match wins:
      1. ``url`` argument
      2. ``external_services.docling.endpoint`` (full URL; ``${DOCLING_ENDPOINT:-...}``)
      3. ``retrieval.docling.host`` + ``retrieval.docling.endpoint``
      4. ``http://localhost:5001/v1/convert/file``

    ``execute({"path": ...})`` converts a file on disk and returns
    ``{"status": "ok", "filename", "markdown", "seconds"}`` or a ``status`` of
    ``error`` / ``connection_error`` with an ``error`` message. The payload names
    the file rather than carrying its bytes: governance checks the payload, and a
    document's bytes are not model input (Shield's InputSizeCheck would refuse
    them). The Markdown that comes back is untrusted text -- screen it before a
    model reads it (Shield / Guardian ``pre_process``). It is returned under
    ``markdown``, not ``output``, so the caller decides how to screen it.
    ``parse(path)`` is the async form.
    """

    layer = "Retrieval ABB"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        monitor=None,
        url: Optional[str] = None,
        timeout: float = 300.0,
        do_ocr: bool = True,
        transport: Optional[httpx.BaseTransport] = None,
        **kwargs,
    ):
        super().__init__(config or {}, monitor=monitor, **kwargs)
        self.url = url or self._configured_url(self.config)
        self.timeout = timeout
        self.do_ocr = do_ocr
        self._transport = transport   # tests pass an httpx.MockTransport
        self.logger.info(f"[DoclingParser] Initialized - endpoint: {self.url}")

    @staticmethod
    def _configured_url(config: Dict[str, Any]) -> str:
        ext = ((config.get("external_services") or {}).get("docling") or {}).get("endpoint")
        if ext:
            return _expand(ext)
        conf = (config.get("retrieval") or {}).get("docling") or {}
        if conf.get("host"):
            host = _expand(conf["host"]).rstrip("/")
            return host + _expand(conf.get("endpoint", "/v1/convert/file"))
        return DEFAULT_URL

    def _form(self) -> Dict[str, str]:
        return {"to_formats": "md", "do_ocr": "true" if self.do_ocr else "false"}

    def _result(self, resp: httpx.Response, filename: str, started: float) -> Dict[str, Any]:
        if resp.status_code != 200:
            self.logger.warning(f"[DoclingParser] HTTP {resp.status_code}: {resp.text[:200]}")
            return {"status": "error", "error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
        data = resp.json()
        doc = data.get("document") or {}
        markdown = doc.get("md_content") or ""
        if data.get("status") not in (None, "success") or not markdown.strip():
            errors = data.get("errors") or []
            return {"status": "error", "error": f"Docling status {data.get('status')}: {errors}"[:500]}
        seconds = round(time.monotonic() - started, 1)
        self.logger.info(f"[DoclingParser] Converted '{filename}' ({len(markdown)} chars, {seconds}s)")
        return {"status": "ok", "markdown": markdown, "seconds": seconds, "data": data}

    # ------------------------------------------------------------------
    # Sync: file bytes in, Markdown out
    # ------------------------------------------------------------------
    def convert(self, filename: str, content: bytes, max_retries: int = 3) -> Dict[str, Any]:
        for attempt in range(1, max_retries + 1):
            started = time.monotonic()
            try:
                with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                    resp = client.post(
                        self.url,
                        files={"files": (filename, content, _mime(filename))},
                        data=self._form(),
                    )
                return self._result(resp, filename, started)
            except httpx.ConnectError as e:
                self.logger.error(f"[DoclingParser] Connection failed (attempt {attempt}): {e}")
                if attempt == max_retries:
                    return {"status": "connection_error", "error": str(e)}
                time.sleep(2 ** (attempt - 1))
            except Exception as e:
                self.logger.error(f"[DoclingParser] Unexpected error: {e}")
                return {"status": "error", "error": str(e)}
        return {"status": "error", "error": "Max retries exceeded"}

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = Path(payload["path"])
        filename = payload.get("filename") or path.name
        if not path.is_file():
            result = {"status": "error", "error": f"File not found: {path}"}
        else:
            result = self.convert(filename, path.read_bytes())
        self.publish_event({
            "type": "DocumentConverted" if result["status"] == "ok" else "DocumentConversionFailed",
            "agent": "DoclingParser",
            "filename": filename,
            "chars": len(result.get("markdown") or ""),
        })
        return {"filename": filename, **{k: v for k, v in result.items() if k != "data"}}

    # ------------------------------------------------------------------
    # Async: a file on disk
    # ------------------------------------------------------------------
    async def parse(self, file_path: str, max_retries: int = 3) -> Dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "error": f"File not found: {path}"}
        content = path.read_bytes()
        for attempt in range(1, max_retries + 1):
            started = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        self.url,
                        files={"files": (path.name, content, _mime(path.name))},
                        data=self._form(),
                    )
                return self._result(resp, path.name, started)
            except httpx.ConnectError as e:
                self.logger.error(f"[DoclingParser] Connection failed (attempt {attempt}): {e}")
                if attempt == max_retries:
                    return {"status": "connection_error", "error": str(e)}
                await asyncio.sleep(2 ** (attempt - 1))
            except Exception as e:
                self.logger.error(f"[DoclingParser] Unexpected error: {e}")
                return {"status": "error", "error": str(e)}
        return {"status": "error", "error": "Max retries exceeded"}
