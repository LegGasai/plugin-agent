from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Request

from plugin_agent.api.deps import get_assembly

router = APIRouter()


@router.get("/sessions/{session_id}")
async def get_session(request: Request, session_id: str) -> dict[str, Any]:
    return {"session": get_assembly(request).get_session(unquote(session_id))}


@router.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: str) -> dict[str, Any]:
    return get_assembly(request).delete_session(unquote(session_id))


@router.get("/sessions/{session_id}/messages")
async def session_messages(request: Request, session_id: str) -> dict[str, Any]:
    return {"messages": get_assembly(request).list_session_messages(unquote(session_id))}
