from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from plugin_agent.api.deps import get_assembly, read_json

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, Any]:
    assembly = get_assembly(request).assemble()
    return {"capabilities": assembly["capabilities"]}


@router.get("/tools")
async def tools(request: Request) -> dict[str, Any]:
    assembly = get_assembly(request).assemble()
    return {"tools": assembly["tools"]}


@router.post("/invoke")
async def invoke(request: Request) -> dict[str, Any]:
    payload = await read_json(request)
    kernel = get_assembly(request).build_kernel(payload.get("plugin_ids"), payload.get("configs"))
    return kernel.invoke(payload["capability"], payload.get("payload", {})).payload


@router.post("/dev/validate-plugin")
async def validate_plugin(request: Request) -> dict[str, Any]:
    return get_assembly(request).validate_plugin(await read_json(request))
