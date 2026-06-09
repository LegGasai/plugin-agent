from __future__ import annotations

from typing import Any

from plugin_agent_sdk import ToolDefinition
from plugin_agent_sdk import Plugin as PluginBase


class ToolRuntimePlugin(PluginBase):
    def __init__(self, config: dict[str, Any] | None = None, instance_id: str | None = None) -> None:
        super().__init__(config, instance_id=instance_id)
        self.tools: dict[str, ToolDefinition] = {}

    def after_start_all(self, kernel) -> None:
        self._refresh_tools(kernel)

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        assert self.kernel is not None
        self._refresh_tools(self.kernel)
        if capability == "tool.registry.list":
            return {"tools": [tool.model_dump() for tool in sorted(self.tools.values(), key=lambda item: item.tool_id)]}
        if capability == "tool.invoke":
            tool_id = payload["tool_id"]
            if tool_id not in self.tools:
                raise ValueError(f"tool {tool_id} is not registered")
            tool = self.tools[tool_id]
            arguments = payload.get("arguments", {})
            self.kernel.schema_registry.validate_payload(tool.input_schema_ref, arguments, "input")
            invoke_payload = arguments
            if tool.invoke_capability == "mcp.tool.call":
                invoke_payload = {"tool_name": tool.tool_id, "arguments": arguments}
            result = self.kernel.invoke(tool.invoke_capability, invoke_payload, context).payload
            return {"tool_id": tool_id, "result": result.get("result", result), "provider_capability": tool.invoke_capability}
        return super().invoke(capability, payload, context)

    def _refresh_tools(self, kernel) -> None:
        self.tools = {tool.tool_id: tool for tool in kernel.collect_tool_definitions()}
