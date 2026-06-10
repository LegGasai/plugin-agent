from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse

from plugin_agent.kernel import KernelInvokeError

logger = logging.getLogger(__name__)


def sse_response(events: Iterable[dict[str, Any]]) -> StreamingResponse:
    def stream() -> Iterable[bytes]:
        try:
            for event in events:
                data = json.dumps(event, ensure_ascii=False)
                yield f"event: {event['type']}\ndata: {data}\n\n".encode("utf-8")
        except Exception as exc:
            logger.exception("SSE stream failed")
            error = exc.error if isinstance(exc, KernelInvokeError) else str(exc)
            event = {"type": "run_failed", "sequence": -1, "run_id": "http-stream", "payload": {"error": error}}
            data = json.dumps(event, ensure_ascii=False)
            yield f"event: run_failed\ndata: {data}\n\n".encode("utf-8")

    return StreamingResponse(stream(), media_type="text/event-stream")


def json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)
