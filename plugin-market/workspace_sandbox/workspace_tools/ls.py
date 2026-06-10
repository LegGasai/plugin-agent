from __future__ import annotations

from typing import Any

from workspace_tools.context import WorkspaceContext


def list_directory(workspace: WorkspaceContext, payload: dict[str, Any]) -> dict[str, Any]:
    path = workspace.resolve_existing(str(payload.get("path") or "."))
    if not path.is_dir():
        raise ValueError("ls path must be a directory")
    recursive = bool(payload.get("recursive", False))
    include_hidden = bool(payload.get("include_hidden", payload.get("includeHidden", False)))
    max_entries = int(payload.get("max_entries", payload.get("maxEntries", 200)))
    entries: list[str] = []

    def visit(directory) -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = workspace.relative(child)
            if not include_hidden and workspace.is_hidden_or_noisy(relative):
                continue
            entries.append(f"{relative}/" if child.is_dir() else relative)
            if recursive and child.is_dir():
                visit(child)

    visit(path)
    selected = entries[:max_entries]
    return {
        "ok": True,
        "path": workspace.relative(path) or ".",
        "entries": selected,
        "entry_count": len(selected),
        "total_entries": len(entries),
        "truncated": len(entries) > len(selected),
    }
