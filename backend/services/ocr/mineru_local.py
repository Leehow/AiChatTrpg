"""Local MinerU backend — invokes the `mineru` CLI as a subprocess.

Why subprocess instead of `import mineru`:

- MinerU drags in torch + ~5GB of model weights. Importing that into the
  chatrpg main process would tie our venv to MinerU's torch version
  (currently torch ≥ 2.4) and bloat startup by 5–10 seconds even when
  OCR isn't used.
- Subprocess isolation means the user installs MinerU into any Python
  environment they want (conda, pipx, separate venv) and we just shell
  out. Upgrades are decoupled.
- Each call pays a 5–15 sec model-load cost. For the rulebook/module
  use case (parsing happens once, takes minutes total) this is fine.
  If it ever matters we can switch to `mineru-api` (HTTP server with
  the model resident) without changing the OCRBackend interface.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Union

from .base import OCRBackend, OCRError, OCRResult
from .result_parser import find_artifact_dir, parse_artifact_dir


# MinerU prints lines like:
#   "Processing page 12/247: ..."
#   "[INFO] Doing layout analysis on page 12 of 247"
# We grep both shapes so the UI can show a real progress bar.
_PROGRESS_RES = (
    re.compile(r"page\s+(\d+)\s*[/of]+\s*(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s*/\s*(\d+)\s*pages?", re.IGNORECASE),
)


@dataclass
class ProgressEvent:
    kind: Literal["log", "progress"]
    line: str = ""
    page: int = 0
    total: int = 0


StreamEvent = Union[ProgressEvent, OCRResult]


def _maybe_progress(line: str) -> ProgressEvent:
    for rx in _PROGRESS_RES:
        m = rx.search(line)
        if m:
            try:
                page = int(m.group(1))
                total = int(m.group(2))
                if total > 0 and 0 < page <= total:
                    return ProgressEvent(
                        kind="progress", line=line, page=page, total=total
                    )
            except (ValueError, IndexError):
                pass
    return ProgressEvent(kind="log", line=line)


@dataclass
class MinerULocalOptions:
    cli: str = "mineru"
    backend: str = "auto"
    lang: str = ""
    no_formula: bool = False
    no_table: bool = False
    timeout_seconds: int = 1800
    # MinerU pulls model weights from huggingface by default. From inside
    # China that's slow / unstable, so we route to ModelScope instead.
    # Set to "huggingface" to opt out.
    model_source: str = "modelscope"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MinerULocalOptions":
        return cls(
            cli=str(data.get("cli") or "mineru"),
            backend=str(data.get("backend") or "auto"),
            lang=str(data.get("lang") or ""),
            no_formula=bool(data.get("no_formula", False)),
            no_table=bool(data.get("no_table", False)),
            timeout_seconds=int(data.get("timeout_seconds") or 1800),
            model_source=str(data.get("model_source") or "modelscope"),
        )


def _build_argv(opts: MinerULocalOptions, input_path: Path, output_dir: Path) -> list[str]:
    # MinerU 3.x flag shape:
    #   -f / --formula BOOLEAN  (default True)
    #   -t / --table   BOOLEAN  (default True)
    #   -b is one of: pipeline | vlm-http-client | hybrid-http-client |
    #                  vlm-auto-engine | hybrid-auto-engine
    # We treat the literal string "auto" in our config as "let mineru
    # choose its own default" — i.e. omit the flag.
    argv: list[str] = [opts.cli, "-p", str(input_path), "-o", str(output_dir)]
    if opts.backend and opts.backend.lower() not in ("", "auto"):
        argv.extend(["-b", opts.backend])
    if opts.lang:
        argv.extend(["-l", opts.lang])
    if opts.no_formula:
        argv.extend(["-f", "False"])
    if opts.no_table:
        argv.extend(["-t", "False"])
    return argv


class MinerULocalBackend(OCRBackend):
    name = "mineru_local"

    def __init__(self, options: MinerULocalOptions):
        self.options = options

    def _subprocess_env(self) -> dict[str, str]:
        """Inherit our env, then layer mineru-specific overrides on top."""
        import os

        env = dict(os.environ)
        if self.options.model_source:
            env["MINERU_MODEL_SOURCE"] = self.options.model_source
        return env

    async def health(self) -> dict[str, Any]:
        cli_path = shutil.which(self.options.cli)
        if cli_path is None:
            return {
                "ok": False,
                "error": f"`{self.options.cli}` not found on PATH",
                "hint": "Install with: pip install -U 'mineru[core]'",
            }
        version = await self._cli_version()
        return {"ok": True, "cli_path": cli_path, "version": version}

    async def _cli_version(self) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.options.cli,
                "--version",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            return (stdout or b"").decode("utf-8", "replace").strip()
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            return ""

    async def extract(self, file_path: Path) -> OCRResult:
        if not file_path.is_file():
            raise OCRError(f"Input file does not exist: {file_path}")
        if shutil.which(self.options.cli) is None:
            raise OCRError(
                f"`{self.options.cli}` not on PATH — install MinerU first "
                "(see docs/install-mineru.md)"
            )

        # Use a temp dir scoped to this call. We hand the artifact dir
        # back to the caller via OCRResult.raw_output_dir; the caller is
        # expected to copy out anything they need before the temp dir is
        # cleaned up. For the test endpoint that's fine — we read the
        # markdown + content_list before returning.
        tmpdir = Path(tempfile.mkdtemp(prefix="mineru-out-"))
        argv = _build_argv(self.options, file_path, tmpdir)

        started = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._subprocess_env(),
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=self.options.timeout_seconds
                )
            except asyncio.TimeoutError as exc:
                proc.kill()
                await proc.wait()
                raise OCRError(
                    f"MinerU timed out after {self.options.timeout_seconds}s"
                ) from exc
        except FileNotFoundError as exc:
            raise OCRError(f"Failed to launch `{self.options.cli}`: {exc}") from exc

        duration = time.perf_counter() - started
        stderr = (stderr_b or b"").decode("utf-8", "replace")
        stdout = (stdout_b or b"").decode("utf-8", "replace")

        if proc.returncode != 0:
            raise OCRError(
                f"mineru exited with code {proc.returncode}\n"
                f"--- stderr ---\n{stderr.strip()}\n"
                f"--- stdout ---\n{stdout.strip()}"
            )

        try:
            artifact_dir = find_artifact_dir(tmpdir)
            parsed = parse_artifact_dir(artifact_dir)
        except FileNotFoundError as exc:
            raise OCRError(
                f"mineru reported success but no markdown was produced under {tmpdir}: {exc}"
            ) from exc

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
                "argv": argv,
                "stderr_tail": stderr.strip()[-500:],
                "images_dropped": int(parsed.get("images_dropped") or 0),
            },
        )

    async def extract_streaming(
        self, file_path: Path
    ) -> AsyncIterator[StreamEvent]:
        """Like extract(), but yields ProgressEvent as MinerU writes
        stderr/stdout lines, then yields the final OCRResult.

        On failure raises OCRError after yielding any partial log lines
        the caller may want to surface.
        """
        if not file_path.is_file():
            raise OCRError(f"Input file does not exist: {file_path}")
        if shutil.which(self.options.cli) is None:
            raise OCRError(
                f"`{self.options.cli}` not on PATH — install MinerU first "
                "(see docs/install-mineru.md)"
            )

        tmpdir = Path(tempfile.mkdtemp(prefix="mineru-out-"))
        argv = _build_argv(self.options, file_path, tmpdir)

        started = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # merge so we get one ordered stream
                env=self._subprocess_env(),
            )
        except FileNotFoundError as exc:
            raise OCRError(f"Failed to launch `{self.options.cli}`: {exc}") from exc

        assert proc.stdout is not None
        deadline = started + self.options.timeout_seconds
        stderr_tail: list[str] = []
        try:
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    proc.kill()
                    await proc.wait()
                    raise OCRError(
                        f"MinerU timed out after {self.options.timeout_seconds}s"
                    )
                try:
                    raw = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=min(remaining, 30)
                    )
                except asyncio.TimeoutError:
                    # No output for 30s — emit a heartbeat so the SSE
                    # connection doesn't go silent. Real timeout is the
                    # outer deadline check above.
                    yield ProgressEvent(kind="log", line="(still working...)")
                    continue
                if not raw:
                    break  # EOF
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                stderr_tail.append(line)
                if len(stderr_tail) > 200:
                    stderr_tail = stderr_tail[-200:]
                yield _maybe_progress(line)
        finally:
            if proc.returncode is None:
                try:
                    await proc.wait()
                except Exception:
                    pass

        duration = time.perf_counter() - started
        if proc.returncode != 0:
            raise OCRError(
                f"mineru exited with code {proc.returncode}\n"
                f"--- last 30 stderr lines ---\n"
                + "\n".join(stderr_tail[-30:])
            )

        try:
            artifact_dir = find_artifact_dir(tmpdir)
            parsed = parse_artifact_dir(artifact_dir)
        except FileNotFoundError as exc:
            raise OCRError(
                f"mineru reported success but no markdown was produced under {tmpdir}: {exc}"
            ) from exc

        yield OCRResult(
            backend=self.name,
            markdown=parsed["markdown"],
            page_count=int(parsed.get("page_count") or 0),
            duration_seconds=round(duration, 2),
            content_list=parsed.get("content_list") or [],
            middle=parsed.get("middle"),
            image_paths=parsed.get("image_paths") or [],
            raw_output_dir=parsed.get("raw_output_dir"),
            extra={
                "argv": argv,
                "stderr_tail": "\n".join(stderr_tail[-30:]),
                "images_dropped": int(parsed.get("images_dropped") or 0),
            },
        )
