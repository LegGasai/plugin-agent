from __future__ import annotations

from fastapi import APIRouter

from plugin_agent.api.agent import router as agent_router
from plugin_agent.api.plugin import router as plugin_router
from plugin_agent.api.runtime import router as runtime_router
from plugin_agent.api.session import router as session_router

api_router = APIRouter(prefix="/api")


def register_router(router: APIRouter, prefix: str = "", tags: list[str] | None = None) -> None:
    api_router.include_router(router, prefix=prefix, tags=tags or [])


register_router(runtime_router, tags=["Runtime"])
register_router(plugin_router, tags=["Plugins"])
register_router(agent_router, tags=["Agents"])
register_router(session_router, tags=["Sessions"])
