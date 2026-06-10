from __future__ import annotations

import json
from typing import Any

from plugin_agent_sdk import Plugin as PluginBase


class SummaryContextCompressorPlugin(PluginBase):
    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability != "context.compressor.compress":
            return super().invoke(capability, payload, context)
        max_chars = int(self.config.get("max_summary_chars", 1200))
        parts = []
        for message in payload["messages"]:
            role = message.get("role", "unknown")
            content = message.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            parts.append(f"{role}: {content}")
        summary = "\n".join(parts)
        if len(summary) > max_chars:
            summary = summary[-max_chars:]
        return {"summary": summary, "provider": {"plugin_id": self.id, "instance_id": self.instance_id}}
