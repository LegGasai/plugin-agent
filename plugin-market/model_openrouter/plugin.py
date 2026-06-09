from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from typing import Any

from plugin_agent_sdk import Plugin as PluginBase


class OpenAIChatModelPluginBase(PluginBase):
    def start(self, kernel) -> None:
        super().start(kernel)
        if not self.config.get("api_key"):
            raise ValueError("missing required config: api_key")

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability != "model.chat":
            return super().invoke(capability, payload, context)
        api_key = self.config.get("api_key")
        if not api_key:
            raise RuntimeError(f"{self.id} requires api_key in its plugin instance config")
        model = self.config.get("model", "gpt-4o-mini")
        base_url = self.config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        body_messages = []
        system_prompt = payload.get("system_prompt")
        if system_prompt:
            body_messages.append({"role": "system", "content": system_prompt})
        body_messages.extend(payload["messages"])
        body = {"model": model, "messages": body_messages, "tools": payload.get("tools", [])}
        if not body["tools"]:
            body.pop("tools")
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        timeout = int(self.config.get("timeout_seconds", 60))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
        choice = raw["choices"][0]["message"]
        return {"message": self._normalize_message(choice), "raw": raw}

    def stream(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> Iterator[dict[str, Any]]:
        if capability != "model.chat.stream":
            yield from super().stream(capability, payload, context)
            return
        api_key = self.config.get("api_key")
        if not api_key:
            raise RuntimeError(f"{self.id} requires api_key in its plugin instance config")
        model = self.config.get("model", "gpt-4o-mini")
        base_url = self.config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        body_messages = []
        system_prompt = payload.get("system_prompt")
        if system_prompt:
            body_messages.append({"role": "system", "content": system_prompt})
        body_messages.extend(payload["messages"])
        body = {"model": model, "messages": body_messages, "tools": payload.get("tools", []), "stream": True}
        if not body["tools"]:
            body.pop("tools")
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        timeout = int(self.config.get("timeout_seconds", 60))
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        sequence = 0
        run_id = context.get("run_id", "model-stream")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content") or ""
                if content:
                    content_parts.append(content)
                    yield {"type": "model_delta", "sequence": sequence, "run_id": run_id, "payload": {"delta": content}}
                    sequence += 1
                self._accumulate_tool_call_deltas(tool_calls, delta.get("tool_calls") or [])
        message = {"role": "assistant", "content": "".join(content_parts), "tool_calls": self._normalized_stream_tool_calls(tool_calls)}
        yield {"type": "assistant_message", "sequence": sequence, "run_id": run_id, "payload": {"message": message}}

    def _normalize_message(self, message: dict[str, Any]) -> dict[str, Any]:
        tool_calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            raw_args = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                arguments = {"_raw": raw_args}
            tool_calls.append({"id": call.get("id"), "tool_id": function.get("name"), "arguments": arguments})
        return {"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls}

    def _accumulate_tool_call_deltas(self, tool_calls: dict[int, dict[str, Any]], deltas: list[dict[str, Any]]) -> None:
        for delta in deltas:
            index = int(delta.get("index", 0))
            current = tool_calls.setdefault(index, {"id": delta.get("id"), "name": "", "arguments": ""})
            if delta.get("id"):
                current["id"] = delta["id"]
            function = delta.get("function") or {}
            if function.get("name"):
                current["name"] += function["name"]
            if function.get("arguments"):
                current["arguments"] += function["arguments"]

    def _normalized_stream_tool_calls(self, tool_calls: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for index in sorted(tool_calls):
            call = tool_calls[index]
            raw_args = call.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError:
                arguments = {"_raw": raw_args}
            normalized.append({"id": call.get("id") or f"call-{index}", "tool_id": call.get("name", ""), "arguments": arguments})
        return normalized


class OpenRouterModelPlugin(OpenAIChatModelPluginBase):
    pass
