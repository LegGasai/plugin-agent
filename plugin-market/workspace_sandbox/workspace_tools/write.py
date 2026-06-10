from __future__ import annotations

from typing import Any

from workspace_tools.context import WorkspaceContext


def write_file(workspace: WorkspaceContext, payload: dict[str, Any]) -> dict[str, Any]:
    path = workspace.resolve_for_create(str(payload["path"]))
    workspace.ensure_writable(path)
    content = str(payload.get("content", ""))
    create_only = bool(payload.get("create_only", payload.get("createOnly", False)))
    exists = path.exists()
    if exists and create_only:
        raise ValueError("file already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "path": workspace.relative(path),
        "operation": "updated" if exists else "created",
        "bytes": len(content.encode("utf-8")),
    }
