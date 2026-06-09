from __future__ import annotations

import json
from typing import Any

from plugin_agent_sdk import Plugin as PluginBase


class ModelContextCompressorPlugin(PluginBase):
    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability != "context.compress":
            return super().invoke(capability, payload, context)
        assert self.kernel is not None

        transcript = self._format_messages(payload["messages"])
        response = self.kernel.invoke(
            "model.chat",
            {
                "system_prompt": self.config.get("system_prompt", ""),
                "messages": [{"role": "user", "content": transcript}],
                "tools": [],
            },
            context,
        ).payload
        summary = response["message"].get("content", "").strip()
        max_chars = int(self.config.get("max_summary_chars", 4000))
        if len(summary) > max_chars:
            summary = summary[-max_chars:]
        return {"summary": summary}

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        lines = []
        for index, message in enumerate(messages, start=1):
            role = message.get("role", "unknown")
            content = message.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            lines.append(f"{index}. {role}: {content}")
        return "\n".join(lines)
