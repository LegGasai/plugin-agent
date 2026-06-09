from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from plugin_agent_sdk import Plugin as PluginBase


class BasicToolPlugin(PluginBase):
    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability == "tool.echo":
            return {"result": payload["text"]}
        if capability == "tool.time_now":
            timezone = payload.get("timezone", self.config.get("timezone", {}).get("default", "UTC"))
            try:
                tz = ZoneInfo(timezone)
            except Exception:
                tz = ZoneInfo("UTC")
                timezone = "UTC"
            return {"result": {"current_time": datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S"), "timezone": timezone}}
        if capability == "tool.math_add":
            return {"result": payload["a"] + payload["b"]}
        return super().invoke(capability, payload, context)
