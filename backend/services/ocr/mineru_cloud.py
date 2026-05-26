"""Cloud MinerU backend — talks to mineru.net via the public REST API.

Workflow:
  1. POST  {base}/file-urls/batch   → presigned upload URLs
  2. PUT   <presigned>              → upload PDF binary
  3. GET   {base}/extract/results/batch/{batch_id}
                                    → poll until state == done
  4. GET   <full_zip_url>           → download result archive
  5. unzip → reuse local result_parser

Reference: https://mineru.net/apiManage/docs
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .base import OCRBackend, OCRError, OCRResult
from .result_parser import extract_zip, parse_artifact_dir


@dataclass
class MinerUCloudOptions:
    api_key: str
    base_url: str = "https://mineru.net/api/v4"
    model_version: str = "vlm"
    poll_interval_seconds: float = 3.0
    poll_timeout_seconds: int = 1800
    request_timeout_seconds: float = 120.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MinerUCloudOptions":
        return cls(
            api_key=str(data.get("api_key") or ""),
            base_url=str(data.get("base_url") or "https://mineru.net/api/v4").rstrip("/"),
            model_version=str(data.get("model_version") or "vlm"),
            poll_interval_seconds=float(data.get("poll_interval_seconds") or 3.0),
            poll_timeout_seconds=int(data.get("poll_timeout_seconds") or 1800),
        )


class MinerUCloudBackend(OCRBackend):
    name = "mineru_cloud"

    def __init__(self, options: MinerUCloudOptions):
        if not options.api_key:
            raise OCRError("mineru_cloud requires an api_key")
        self.options = options

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.options.base_url,
            timeout=self.options.request_timeout_seconds,
            headers={
                "Authorization": f"Bearer {self.options.api_key}",
                "Accept": "*/*",
            },
        )

    async def health(self) -> dict[str, Any]:
        # Cheap probe: request a 1-file batch URL with a fake filename.
        # Full submit would consume quota; this just validates auth.
        try:
            async with self._client() as client:
                resp = await client.post(
                    "/file-urls/batch",
                    json={
                        "files": [{"name": "ping.pdf", "data_id": "ping"}],
                        "model_version": self.options.model_version,
                    },
                )
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if resp.status_code == 401 or resp.status_code == 403:
            return {"ok": False, "error": "API key rejected (401/403)"}
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        try:
            data = resp.json()
        except ValueError:
            return {"ok": False, "error": "non-JSON response"}
        return {"ok": data.get("code") == 0, "raw": data.get("msg", "")}

    async def extract(self, file_path: Path) -> OCRResult:
        if not file_path.is_file():
            raise OCRError(f"Input file does not exist: {file_path}")
        started = time.perf_counter()

        async with self._client() as client:
            upload_url, batch_id = await self._request_upload_url(client, file_path.name)
            await self._upload(client, upload_url, file_path)
            full_zip_url = await self._poll(client, batch_id)
            zip_bytes = await self._download(client, full_zip_url)

        duration = time.perf_counter() - started

        # Unzip to a temp dir and parse using the local result parser.
        tmpdir = Path(tempfile.mkdtemp(prefix="mineru-cloud-"))
        zip_path = tmpdir / "result.zip"
        zip_path.write_bytes(zip_bytes)
        try:
            artifact_dir = extract_zip(zip_path, tmpdir / "unpacked")
            parsed = parse_artifact_dir(artifact_dir)
        except (FileNotFoundError, OSError) as exc:
            raise OCRError(f"Failed to parse mineru.net result archive: {exc}") from exc

        return OCRResult(
            backend=self.name,
            markdown=parsed["markdown"],
            page_count=int(parsed.get("page_count") or 0),
            duration_seconds=round(duration, 2),
            content_list=parsed.get("content_list") or [],
            middle=parsed.get("middle"),
            image_paths=parsed.get("image_paths") or [],
            raw_output_dir=parsed.get("raw_output_dir"),
            extra={
                "batch_id": batch_id,
                "zip_url": full_zip_url,
                "images_dropped": int(parsed.get("images_dropped") or 0),
            },
        )

    async def _request_upload_url(
        self, client: httpx.AsyncClient, filename: str
    ) -> tuple[str, str]:
        resp = await client.post(
            "/file-urls/batch",
            json={
                "files": [{"name": filename, "data_id": filename}],
                "model_version": self.options.model_version,
            },
        )
        if resp.status_code >= 400:
            raise OCRError(
                f"file-urls/batch failed: HTTP {resp.status_code} {resp.text[:300]}"
            )
        data = resp.json()
        if data.get("code") != 0:
            raise OCRError(f"file-urls/batch error: {data.get('msg')}")
        body = data.get("data") or {}
        urls = body.get("file_urls") or []
        batch_id = body.get("batch_id")
        if not urls or not batch_id:
            raise OCRError(f"file-urls/batch returned no urls/batch_id: {data}")
        return urls[0], batch_id

    async def _upload(self, client: httpx.AsyncClient, url: str, file_path: Path) -> None:
        # Presigned URL — no auth header needed (and including ours can
        # confuse some object stores).
        async with httpx.AsyncClient(timeout=self.options.request_timeout_seconds) as raw:
            with file_path.open("rb") as f:
                resp = await raw.put(url, content=f.read())
        if resp.status_code >= 400:
            raise OCRError(f"PUT upload failed: HTTP {resp.status_code} {resp.text[:300]}")

    async def _poll(self, client: httpx.AsyncClient, batch_id: str) -> str:
        deadline = time.perf_counter() + self.options.poll_timeout_seconds
        while True:
            resp = await client.get(f"/extract-results/batch/{batch_id}")
            if resp.status_code >= 400:
                raise OCRError(
                    f"poll failed: HTTP {resp.status_code} {resp.text[:300]}"
                )
            data = resp.json()
            if data.get("code") != 0:
                raise OCRError(f"poll error: {data.get('msg')}")
            results = ((data.get("data") or {}).get("extract_result")) or []
            if not results:
                raise OCRError(f"poll returned no extract_result: {data}")
            row = results[0]
            state = row.get("state")
            if state == "done":
                full_zip = row.get("full_zip_url")
                if not full_zip:
                    raise OCRError(f"task done but no full_zip_url: {row}")
                return full_zip
            if state == "failed":
                raise OCRError(f"mineru.net task failed: {row.get('err_msg')}")
            if time.perf_counter() > deadline:
                raise OCRError(
                    f"mineru.net task timed out after "
                    f"{self.options.poll_timeout_seconds}s (state={state})"
                )
            await asyncio.sleep(self.options.poll_interval_seconds)

    async def _download(self, client: httpx.AsyncClient, url: str) -> bytes:
        # Result CDN URL — fetch raw, no Authorization header.
        async with httpx.AsyncClient(timeout=self.options.request_timeout_seconds) as raw:
            resp = await raw.get(url)
        if resp.status_code >= 400:
            raise OCRError(f"download failed: HTTP {resp.status_code}")
        return resp.content
