from __future__ import annotations

from typing import Any

from workspace_tools.context import WorkspaceContext


def edit_file(workspace: WorkspaceContext, payload: dict[str, Any]) -> dict[str, Any]:
    file_path = str(payload.get("file_path") or payload.get("path") or "")
    old_text = str(payload.get("old_string", payload.get("old_text", "")))
    new_text = str(payload.get("new_string", payload.get("new_text", "")))
    replace_all = bool(payload.get("replace_all", False))
    if not file_path:
        raise ValueError("file_path is required")
    if old_text == "":
        raise ValueError("old_string is required")
    if old_text == new_text:
        raise ValueError("old_string and new_string are identical")
    path = workspace.resolve_existing(file_path)
    workspace.ensure_writable(path)
    previous = workspace.reads.get(str(path))
    if previous is None:
        raise ValueError("file must be read before edit")
    stat = path.stat()
    if previous != (stat.st_mtime, stat.st_size):
        raise ValueError("file has changed since it was read")
    text = path.read_text(encoding="utf-8")
    matches = text.count(old_text)
    if matches == 0:
        raise ValueError("string to replace not found")
    if matches > 1 and not replace_all:
        raise ValueError(f"found {matches} matches; set replace_all=true")
    next_text = text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
    path.write_text(next_text, encoding="utf-8")
    next_stat = path.stat()
    workspace.reads[str(path)] = (next_stat.st_mtime, next_stat.st_size)
    return {
        "ok": True,
        "path": workspace.relative(path),
        "operation": "edited",
        "replacements": matches if replace_all else 1,
        "bytes": len(next_text.encode("utf-8")),
    }
