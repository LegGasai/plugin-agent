from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Request

from plugin_agent.api.deps import get_assembly, read_json
from plugin_agent.api.uploads import is_multipart_request, write_multipart_upload

router = APIRouter()


@router.get("/installed-plugin-packages")
async def installed_plugin_packages(request: Request, tag: str | None = None) -> dict[str, Any]:
    return {"plugin_packages": get_assembly(request).list_installed_plugin_packages(tag=tag)}


@router.get("/plugin-packages")
async def plugin_packages(request: Request, tag: str | None = None) -> dict[str, Any]:
    return {"plugin_packages": get_assembly(request).list_plugin_packages(tag=tag)}


@router.post("/plugin-packages/refresh")
async def refresh_plugin_packages(request: Request) -> dict[str, Any]:
    return get_assembly(request).refresh_plugin_packages()


@router.get("/plugins")
async def plugins(request: Request) -> dict[str, Any]:
    return {"plugins": get_assembly(request).list_plugin_catalog()}


@router.put("/plugins/{plugin_id}/config")
async def update_plugin_config(request: Request, plugin_id: str) -> dict[str, Any]:
    payload = await read_json(request)
    plugin = get_assembly(request).update_plugin_config(unquote(plugin_id), payload.get("config", {}))
    return {"plugin": plugin}


@router.get("/marketplace/plugins")
async def marketplace_plugins(request: Request, tag: str | None = None) -> dict[str, Any]:
    return get_assembly(request).marketplace(tag=tag)


@router.post("/marketplace/upload")
async def marketplace_upload(request: Request) -> dict[str, Any]:
    if is_multipart_request(request):
        with tempfile.TemporaryDirectory(prefix="plugin-agent-upload-") as temp_dir:
            upload_path = await write_multipart_upload(request, Path(temp_dir))
            return get_assembly(request).reserve_upload({"path": str(upload_path)})
    if os.environ.get("PLUGIN_AGENT_ALLOW_PATH_UPLOAD") not in {"1", "true", "TRUE", "yes", "YES"}:
        raise ValueError("JSON path uploads are disabled; use multipart/form-data")
    return get_assembly(request).reserve_upload(await read_json(request))


@router.post("/marketplace/install")
async def marketplace_install(request: Request) -> dict[str, Any]:
    return get_assembly(request).install_market_plugin(await read_json(request))


@router.delete("/installed-plugin-packages/{package_id:path}")
async def uninstall_installed_plugin(request: Request, package_id: str, version: str | None = None) -> dict[str, Any]:
    return get_assembly(request).uninstall_installed_plugin(unquote(package_id), version=version)


@router.put("/plugin-instances/{instance_id}/config")
async def update_plugin_instance_config(request: Request, instance_id: str) -> dict[str, Any]:
    payload = await read_json(request)
    plugin_instance = get_assembly(request).update_plugin_instance_config(
        unquote(instance_id), payload.get("config", {})
    )
    return {"plugin_instance": plugin_instance}


@router.post("/plugin-instances/{instance_id}/restart")
async def restart_plugin_instance(request: Request, instance_id: str) -> dict[str, Any]:
    return {"plugin_instance": get_assembly(request).restart_plugin_instance(unquote(instance_id))}
