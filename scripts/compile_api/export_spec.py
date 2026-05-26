"""Export OpenAPI + SSE event JSON Schema for client codegen.

Run from repo root:
    python scripts/compile_api/export_spec.py

Outputs:
    contracts/openapi.json     — FastAPI's OpenAPI 3.1 spec
    contracts/sse_events.json  — JSON Schema for the SSE event union

Both are committed; downstream codegen (this repo's React client and any
chatlab consumer) reads from the committed files so the compiler is
reproducible without booting the backend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
CONTRACTS_DIR = REPO_ROOT / "contracts"

sys.path.insert(0, str(BACKEND_DIR))

# These imports require BACKEND_DIR on sys.path.
from main import app  # noqa: E402
from schemas.sse_events import (  # noqa: E402
    SseContentEvent,
    SseDoneEvent,
    SseErrorEvent,
    SseMarkerEvent,
    SseMetadataEvent,
    SseSegmentErrorEvent,
    SseSideEffectEvent,
    SseThinkingEvent,
)


def export_openapi() -> Path:
    spec = app.openapi()
    out = CONTRACTS_DIR / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def export_sse_events() -> Path:
    events = [
        SseMetadataEvent,
        SseThinkingEvent,
        SseContentEvent,
        SseMarkerEvent,
        SseSideEffectEvent,
        SseDoneEvent,
        SseErrorEvent,
        SseSegmentErrorEvent,
    ]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ChatRPG SSE Event",
        "description": "Discriminated union by `type` field.",
        "discriminator": {"propertyName": "type"},
        "oneOf": [evt.model_json_schema() for evt in events],
    }
    out = CONTRACTS_DIR / "sse_events.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    spec_path = export_openapi()
    sse_path = export_sse_events()
    print(f"wrote {spec_path.relative_to(REPO_ROOT)}")
    print(f"wrote {sse_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
