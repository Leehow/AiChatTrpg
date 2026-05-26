import json
from collections.abc import AsyncIterator
from typing import Any


def encode_event(payload: dict[str, Any]) -> str:
    """Format a JSON payload as a single SSE 'data:' frame.

    Always ends with two newlines so EventSource parsers see a complete event.
    Avoid embedding raw newlines within JSON values; json.dumps escapes them.
    """
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def passthrough(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    async for event in events:
        yield encode_event(event)
