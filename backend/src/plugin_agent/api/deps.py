from __future__ import annotations

from typing import Any

from fastapi import Request

from plugin_agent.assembly import AgentAssemblyService


def get_assembly(request: Request) -> AgentAssemblyService:
    return request.app.state.plugin_agent.assembly


async def read_json(request: Request) -> dict[str, Any]:
    if not (await request.body()):
        return {}
    return await request.json()
