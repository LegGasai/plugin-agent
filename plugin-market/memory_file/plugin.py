from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plugin_agent_sdk import Plugin as PluginBase


class FileMemoryPlugin(PluginBase):
    def start(self, kernel):
        super().start(kernel)
        configured = self.config.get("path") or ".plugin-agent/memory.jsonl"
        self.path = Path(configured).expanduser()
        if not self.path.is_absolute():
            self.path = Path.cwd() / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability == "memory.write":
            metadata = dict(payload.get("metadata", {}))
            for key in ("agent_id", "session_id"):
                if context.get(key) and key not in metadata:
                    metadata[key] = context[key]
            item = {"id": self._next_id(), "text": payload["text"], "metadata": metadata}
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            return {"item": item}
        if capability == "memory.query":
            query = payload["query"].lower()
            terms = [term for term in query.split() if term]
            limit = payload.get("limit", 5)
            scoped_context = {key: context.get(key) for key in ("agent_id", "session_id") if context.get(key)}
            matched = [
                item
                for item in reversed(self._read_items())
                if self._matches_scope(item, scoped_context)
                and (not terms or any(term in item["text"].lower() for term in terms))
            ]
            return {"items": matched[:limit]}
        return super().invoke(capability, payload, context)

    def _matches_scope(self, item: dict[str, Any], scoped_context: dict[str, str]) -> bool:
        if not scoped_context:
            return True
        metadata = item.get("metadata") or {}
        return all(metadata.get(key) == value for key, value in scoped_context.items())

    def _read_items(self) -> list[dict[str, Any]]:
        items = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            items.append(json.loads(line))
        return items

    def _next_id(self) -> int:
        return len(self._read_items()) + 1
