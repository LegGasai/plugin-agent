from __future__ import annotations

from typing import Any

from plugin_agent_sdk import Plugin


class GreeterToolPlugin(Plugin):
    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability == "tool.greet":
            name = str(payload["name"]).strip()
            style = payload.get("style", "friendly")
            templates = {
                "friendly": f"你好，{name}！欢迎使用自定义插件。",
                "cheerful": f"你好，{name}！自定义插件已经顺利跑起来啦。",
                "concise": f"你好，{name}。",
            }
            return {"result": {"message": templates.get(style, templates["friendly"]), "name": name, "style": style}}
        return super().invoke(capability, payload, context)
