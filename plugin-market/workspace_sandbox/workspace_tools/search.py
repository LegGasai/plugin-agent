from __future__ import annotations

import fnmatch
import re
from typing import Any

from workspace_tools.context import WorkspaceContext


def grep_files(workspace: WorkspaceContext, payload: dict[str, Any]) -> dict[str, Any]:
    pattern = str(payload["pattern"])
    start = workspace.resolve_existing(str(payload.get("path") or "."))
    include = payload.get("include")
    exclude = payload.get("exclude")
    max_matches = int(payload.get("max_matches", payload.get("maxMatches", 250)))
    matcher = re.compile(pattern)
    files = workspace.walk_files(start if start.is_dir() else start.parent)
    if start.is_file():
        files = [start]
    matches: list[dict[str, Any]] = []
    total = 0
    for file in files:
        rel = workspace.relative(file)
        if include and not fnmatch.fnmatch(rel, str(include)):
            continue
        if exclude and fnmatch.fnmatch(rel, str(exclude)):
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if not matcher.search(line):
                continue
            total += 1
            if len(matches) < max_matches:
                matches.append({"path": rel, "line": index, "text": line})
    return {"ok": True, "matches": matches, "match_count": len(matches), "total_matches": total, "truncated": total > len(matches)}


def glob_files(workspace: WorkspaceContext, payload: dict[str, Any]) -> dict[str, Any]:
    pattern = str(payload["pattern"])
    start = workspace.resolve_existing(str(payload.get("path") or "."))
    if not start.is_dir():
        raise ValueError("glob path must be a directory")
    max_matches = int(payload.get("max_matches", payload.get("maxMatches", 250)))
    matches = [workspace.relative(path) for path in workspace.walk_files(start) if fnmatch.fnmatch(workspace.relative(path), pattern)]
    matches.sort()
    selected = matches[:max_matches]
    return {"ok": True, "matches": selected, "match_count": len(selected), "total_matches": len(matches), "truncated": len(matches) > len(selected)}
