from __future__ import annotations

from typing import Any

from workspace_tools.context import WorkspaceContext


def read_file(workspace: WorkspaceContext, payload: dict[str, Any]) -> dict[str, Any]:
    path = workspace.resolve_existing(str(payload["path"]))
    if path.is_dir():
        raise ValueError("cannot read directory")
    stat = path.stat()
    max_file_bytes = workspace.max_file_bytes()
    if stat.st_size > max_file_bytes:
        raise ValueError(f"file exceeds max_file_bytes: {stat.st_size} > {max_file_bytes}")
    data = path.read_bytes()
    if b"\x00" in data[:8000]:
        raise ValueError("cannot read binary file")
    text = data.decode("utf-8")
    workspace.reads[str(path)] = (stat.st_mtime, stat.st_size)
    lines = text.splitlines()
    offset = max(1, int(payload.get("offset", 1)))
    limit = max(1, int(payload.get("limit", 2000)))
    selected = lines[offset - 1 : offset - 1 + limit]
    numbered = "\n".join(f"{offset + index}: {line}" for index, line in enumerate(selected))
    return {
        "ok": True,
        "path": workspace.relative(path),
        "content": numbered,
        "bytes": len(data),
        "line_count": len(lines),
        "truncated": offset > 1 or offset - 1 + limit < len(lines),
    }
