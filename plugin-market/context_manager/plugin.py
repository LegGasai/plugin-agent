from __future__ import annotations

from typing import Any

from plugin_agent_sdk import Plugin as PluginBase


class ContextManagerPlugin(PluginBase):
    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability != "context.compress":
            return super().invoke(capability, payload, context)
        assert self.kernel is not None

        messages = list(payload["messages"])
        model_messages = list(payload.get("model_messages") or messages)
        compression_config = self.config.get("compression", {})
        preserve_tail = int(payload.get("preserve_tail_messages", compression_config.get("preserve_tail_messages", 1)))
        summary_prefix = compression_config.get("summary_prefix", "Conversation summary so far:")

        compressed = self.kernel.invoke("context.compressor.compress", {"messages": messages}, context).payload
        summary = str(compressed.get("summary", ""))
        return {
            "summary": summary,
            "messages": self._replacement_messages(summary, messages, preserve_tail, summary_prefix),
            "model_messages": self._replacement_messages(summary, model_messages, preserve_tail, summary_prefix),
            "provider_capability": "context.compressor.compress",
            "provider": compressed.get("provider", {}),
        }

    def _replacement_messages(
        self,
        summary: str,
        messages: list[dict[str, Any]],
        preserve_tail: int,
        summary_prefix: str,
    ) -> list[dict[str, Any]]:
        summary_message = {
            "role": "system",
            "content": f"{summary_prefix} {summary}".strip(),
            "metadata": {"compressed_by": self.id},
        }
        if preserve_tail <= 0:
            return [summary_message]
        return [summary_message, *messages[-preserve_tail:]]
