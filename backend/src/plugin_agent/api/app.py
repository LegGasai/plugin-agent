from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from plugin_agent.api.responses import json_error
from plugin_agent.api.router import api_router
from plugin_agent.assembly import AgentAssemblyService
from plugin_agent.kernel import KernelInvokeError

logger = logging.getLogger(__name__)


class AppState:
    def __init__(self, runtime_dir: str | Path | None = None, market_dir: str | Path | None = None) -> None:
        self.assembly = AgentAssemblyService(runtime_dir=runtime_dir, market_dir=market_dir)


def create_app_state(runtime_dir: str | Path | None = None, market_dir: str | Path | None = None) -> AppState:
    return AppState(runtime_dir=runtime_dir, market_dir=market_dir)


def create_app(state: AppState | None = None) -> FastAPI:
    app = FastAPI(title="Plugin Agent API")
    app.state.plugin_agent = state or create_app_state()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    register_exception_handlers(app)
    return app


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(KeyError)
    async def key_error_handler(_request: Request, exc: KeyError) -> JSONResponse:
        return json_error(404, str(exc))

    @app.exception_handler(KernelInvokeError)
    async def kernel_error_handler(request: Request, exc: KernelInvokeError) -> JSONResponse:
        logger.warning("%s %s failed with kernel error: %s", request.method, request.url.path, exc.error.get("code"))
        return JSONResponse({"error": exc.error["message"], "error_detail": exc.error}, status_code=500)

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return json_error(400, str(exc))
