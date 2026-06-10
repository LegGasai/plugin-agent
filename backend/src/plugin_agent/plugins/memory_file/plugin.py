from __future__ import annotations

from pathlib import Path
from typing import Any

from plugin_agent_sdk import Plugin as PluginBase


class FileMemoryPlugin(PluginBase):
    def start(self, kernel):
        super().start(kernel)
        configured = self.config.get("memory_dir")
        self.memory_dir = self._resolve_memory_dir(configured)
        self.max_file_bytes = int(self.config.get("max_file_bytes", 512 * 1024))
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.touch(exist_ok=True)

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability == "memory.read":
            return {"result": self._read(payload)}
        if capability == "memory.write":
            return {"result": self._write(payload, context)}
        return super().invoke(capability, payload, context)

    @property
    def index_path(self) -> Path:
        return self.memory_dir / "MEMORY.md"

    def _resolve_memory_dir(self, configured: str | None) -> Path:
        if not configured:
            return self.plugin_dir / "memory"
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path

    def _read(self, payload: dict[str, Any]) -> dict[str, Any]:
        relative = self._normalize_path(payload.get("path") or "MEMORY.md", allow_index=True)
        target = self._target_path(relative)
        if relative == "MEMORY.md" and not target.exists():
            target.touch()
        self._assert_readable_file(target)
        content = target.read_text(encoding="utf-8")
        result = {"path": relative, "content": content, "bytes": target.stat().st_size}
        if relative == "MEMORY.md":
            result["entries"] = self._read_index()
        return result

    def _write(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        relative = self._normalize_path(payload["path"], allow_index=False)
        description = str(payload.get("description") or "").strip()
        content = str(payload.get("content") or "")
        mode = payload.get("mode") or "replace"
        if not description:
            raise ValueError("memory.write requires description")
        if mode not in {"replace", "append"}:
            raise ValueError("memory.write mode must be replace or append")
        target = self._target_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.is_symlink():
            raise ValueError("memory file path must stay inside the memory directory")
        if mode == "append" and target.exists():
            previous = target.read_text(encoding="utf-8")
            separator = "" if not previous or previous.endswith("\n") else "\n"
            target.write_text(previous + separator + content, encoding="utf-8")
        else:
            target.write_text(content, encoding="utf-8")
        self._upsert_index(relative, description)
        return {"path": relative, "description": description, "bytes": target.stat().st_size, "entries": self._read_index()}

    def _read_index(self) -> list[dict[str, str]]:
        entries = []
        if not self.index_path.exists():
            return entries
        for raw_line in self.index_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            path, description = line.split(":", 1)
            try:
                normalized = self._normalize_path(path.strip(), allow_index=False)
            except ValueError:
                continue
            entries.append({"path": normalized, "description": description.strip()})
        return entries

    def _upsert_index(self, relative: str, description: str) -> None:
        entries = [entry for entry in self._read_index() if entry["path"] != relative]
        entries.append({"path": relative, "description": description})
        self.index_path.write_text(
            "\n".join(f"{entry['path']}: {entry['description']}" for entry in entries) + "\n",
            encoding="utf-8",
        )

    def _target_path(self, relative: str) -> Path:
        target = (self.memory_dir / relative).resolve()
        root = self.memory_dir.resolve()
        if target != root and root not in target.parents:
            raise ValueError("memory file path must stay inside the memory directory")
        return target

    def _normalize_path(self, value: str, allow_index: bool) -> str:
        normalized = str(value).strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or "\x00" in normalized:
            raise ValueError("invalid memory file path")
        parts = normalized.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("memory file path must stay inside the memory directory")
        if normalized == "MEMORY.md":
            if allow_index:
                return normalized
            raise ValueError("memory.write manages MEMORY.md through memory file descriptions")
        if not normalized.endswith(".md"):
            raise ValueError("memory files must be markdown files")
        return normalized

    def _assert_readable_file(self, target: Path) -> None:
        if target.is_symlink():
            raise ValueError("memory file path must stay inside the memory directory")
        if not target.exists() or not target.is_file():
            raise ValueError("memory file does not exist")
        if target.stat().st_size > self.max_file_bytes:
            raise ValueError("memory file is too large to read")
