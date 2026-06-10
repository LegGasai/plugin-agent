from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from plugin_agent.api.deps import get_assembly, read_json
from plugin_agent.api.responses import sse_response

router = APIRouter()


@router.get("/agents")
async def agents(request: Request) -> dict[str, Any]:
    return {"agents": get_assembly(request).list_agents()}


@router.post("/agents")
async def create_agent(request: Request) -> dict[str, Any]:
    payload = await read_json(request)
    agent = get_assembly(request).create_agent(
        payload["name"],
        payload.get("plugin_ids"),
        payload.get("configs"),
        payload.get("description", ""),
        payload.get("plugin_instances"),
        payload.get("capability_bindings"),
    )
    return {"agent": agent}


@router.post("/agents/assemble")
async def assemble_agent(request: Request) -> dict[str, Any]:
    payload = await read_json(request)
    return get_assembly(request).assemble(payload.get("plugin_ids"), payload.get("configs"))


@router.post("/agents/run")
async def run_agent(request: Request) -> dict[str, Any]:
    payload = await read_json(request)
    return get_assembly(request).run_agent(payload["message"], payload.get("plugin_ids"), payload.get("configs"))


@router.post("/agents/stream")
async def stream_agent(request: Request) -> StreamingResponse:
    payload = await read_json(request)
    events = get_assembly(request).stream_agent(payload["message"], payload.get("plugin_ids"), payload.get("configs"))
    return sse_response(events)


@router.get("/agents/{agent_id}")
async def get_agent(request: Request, agent_id: str) -> dict[str, Any]:
    return {"agent": get_assembly(request).get_agent(unquote(agent_id))}


@router.put("/agents/{agent_id}")
async def update_agent(request: Request, agent_id: str) -> dict[str, Any]:
    payload = await read_json(request)
    agent = get_assembly(request).update_agent(
        unquote(agent_id),
        name=payload.get("name"),
        description=payload.get("description"),
        plugin_instances=payload.get("plugin_instances"),
    )
    return {"agent": agent}


@router.delete("/agents/{agent_id}")
async def delete_agent(request: Request, agent_id: str) -> dict[str, Any]:
    return get_assembly(request).delete_agent(unquote(agent_id))


@router.get("/agents/{agent_id}/sessions")
async def agent_sessions(request: Request, agent_id: str) -> dict[str, Any]:
    return {"sessions": get_assembly(request).list_sessions(unquote(agent_id))}


@router.post("/agents/{agent_id}/sessions")
async def create_agent_session(request: Request, agent_id: str) -> dict[str, Any]:
    payload = await read_json(request)
    return {"session": get_assembly(request).create_session(unquote(agent_id), payload.get("title"))}


@router.get("/agents/{agent_id}/capabilities")
async def agent_capabilities(request: Request, agent_id: str) -> dict[str, Any]:
    return {"capabilities": get_assembly(request).agent_capabilities(unquote(agent_id))}


@router.get("/agents/{agent_id}/capability-candidates")
async def agent_capability_candidates(request: Request, agent_id: str) -> dict[str, Any]:
    return {"capabilities": get_assembly(request).agent_capability_candidates(unquote(agent_id))}


@router.get("/agents/{agent_id}/resources")
async def agent_resources(request: Request, agent_id: str) -> dict[str, Any]:
    return {"resources": get_assembly(request).agent_resources(unquote(agent_id))}


@router.get("/agents/{agent_id}/runtime")
async def agent_runtime(request: Request, agent_id: str) -> dict[str, Any]:
    return get_assembly(request).agent_runtime(unquote(agent_id))


@router.put("/agents/{agent_id}/capability-bindings")
async def update_agent_capability_bindings(request: Request, agent_id: str) -> dict[str, Any]:
    payload = await read_json(request)
    agent = get_assembly(request).update_agent_capability_bindings(
        unquote(agent_id), payload.get("capability_bindings", {})
    )
    return {"agent": agent}


@router.post("/agents/{agent_id}/run")
async def run_saved_agent(request: Request, agent_id: str) -> dict[str, Any]:
    payload = await read_json(request)
    return get_assembly(request).run_saved_agent(unquote(agent_id), payload["message"], payload.get("session_id"))


@router.post("/agents/{agent_id}/stream")
async def stream_saved_agent(request: Request, agent_id: str) -> StreamingResponse:
    payload = await read_json(request)
    events = get_assembly(request).stream_saved_agent(unquote(agent_id), payload["message"], payload.get("session_id"))
    return sse_response(events)
