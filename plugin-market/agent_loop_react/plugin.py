from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from collections.abc import Iterator
from typing import Any

from plugin_agent_sdk import Plugin as PluginBase


class ReactAgentLoopPlugin(PluginBase):
    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability != "agent.run":
            return super().invoke(capability, payload, context)
        final_payload: dict[str, Any] | None = None
        failed_payload: dict[str, Any] | None = None
        streamed_events: list[dict[str, Any]] = []
        for event in self.stream("agent.stream", payload, context):
            streamed_events.append(event)
            if event["type"] == "run_completed":
                final_payload = event["payload"]
            elif event["type"] == "run_failed":
                failed_payload = event["payload"]
        if final_payload is not None:
            return {**final_payload, "events": streamed_events}
        if failed_payload is not None:
            return {**failed_payload, "events": streamed_events}
        raise RuntimeError("agent stream ended without a completion event")

    def stream(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> Iterator[dict[str, Any]]:
        if capability != "agent.stream":
            yield from super().stream(capability, payload, context)
            return
        assert self.kernel is not None
        user_text = payload["message"]
        run_id = context.get("run_id") or f"run-{int(time.time() * 1000)}"
        sequence = 0
        events: list[dict[str, Any]] = []
        history_messages = self._history_messages(context)
        transcript: list[dict[str, Any]] = [*history_messages, {"role": "user", "content": user_text}]
        model_messages: list[dict[str, Any]] = [*history_messages, {"role": "user", "content": user_text}]
        tool_audit: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        final_answer = ""
        stop_reason = "max_turns"

        def emit(event_type: str, event_payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal sequence
            event = {"type": event_type, "sequence": sequence, "run_id": run_id, "payload": event_payload}
            sequence += 1
            events.append(event)
            return event

        yield emit("run_started", {"message": user_text})

        try:
            memory = self._load_memory(user_text, context)
        except Exception as exc:
            memory = []
            failure = self._final_payload(str(exc), "error", memory, transcript, events, tool_audit, tool_calls)
            yield emit("run_failed", failure)
            return
        yield emit("memory_loaded", {"items": memory})
        if memory:
            model_messages.insert(0, {"role": "system", "content": self._memory_prompt(memory)})

        selected_skills = self._selected_skills(user_text, context)
        if selected_skills:
            model_messages.insert(0, {"role": "system", "content": self._skills_prompt(selected_skills)})
        yield emit("skills_selected", {"skills": selected_skills})

        tools = self._model_tools()
        tool_name_to_id = {tool["function"]["name"]: tool["tool_id"] for tool in tools}
        model_tool_payload = [{"type": "function", "function": tool["function"]} for tool in tools]
        yield emit("tools_loaded", {"tools": [{"tool_id": tool["tool_id"], "function": tool["function"]} for tool in tools]})

        for turn in range(self.config.get("limits", {}).get("max_turns", 8)):
            try:
                assistant, delta_events = self._model_turn(
                    model_messages,
                    model_tool_payload,
                    {**context, "run_id": run_id, "turn": turn},
                )
                for delta in delta_events:
                    yield emit("model_delta", {"delta": delta})
            except Exception as exc:
                final_answer = str(exc)
                stop_reason = "error"
                yield emit("run_failed", self._final_payload(final_answer, stop_reason, memory, transcript, events, tool_audit, tool_calls))
                break

            assistant = self._normalize_assistant_message(assistant, tool_name_to_id)
            transcript.append(assistant)
            model_messages.append(self._to_model_assistant_message(assistant, tools))
            yield emit("assistant_message", {"turn": turn, "message": assistant})

            pending_calls = assistant.get("tool_calls", [])
            if not pending_calls:
                final_answer = assistant.get("content", "")
                stop_reason = "final"
                final_payload = self._final_payload(final_answer, stop_reason, memory, transcript, events, tool_audit, tool_calls)
                self._write_memory(user_text, final_answer, tool_calls, context)
                yield emit("run_completed", final_payload)
                break

            for call in pending_calls:
                started = time.perf_counter()
                tool_id = call["tool_id"]
                arguments = call.get("arguments", {})
                yield emit("tool_call_started", {"tool_call_id": call["id"], "tool_name": tool_id, "input": arguments})
                try:
                    tool_result = self._invoke_tool_with_timeout(tool_id, arguments, context)
                    ok = True
                    error = None
                    observation = tool_result["result"]
                except Exception as exc:
                    ok = False
                    error = {"code": "TOOL_CALL_ERROR", "message": str(exc)}
                    observation = {"error": str(exc)}

                duration_ms = int((time.perf_counter() - started) * 1000)
                transcript.append({"role": "tool", "tool_call_id": call["id"], "name": tool_id, "content": observation})
                model_messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(observation, ensure_ascii=False)})
                audit_entry = {"tool_call_id": call["id"], "tool_name": tool_id, "input": arguments, "ok": ok, "content": observation, "error": error, "duration_ms": duration_ms}
                tool_audit.append(audit_entry)
                tool_calls.append({"tool_call_id": call["id"], "tool_id": tool_id, "arguments": arguments, "result": observation})
                yield emit("tool_call_completed", {"tool_call_id": call["id"], "tool_name": tool_id, "result": observation, "ok": ok, "error": error})
            compressed = self._maybe_compress_context(transcript, model_messages, context)
            if compressed is not None:
                yield emit("context_compressed", compressed)

        if stop_reason == "max_turns":
            final_payload = self._final_payload(final_answer, stop_reason, memory, transcript, events, tool_audit, tool_calls)
            self._write_memory(user_text, final_answer, tool_calls, context)
            yield emit("run_completed", final_payload)

    def _invoke_tool_with_timeout(self, tool_id: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        assert self.kernel is not None
        timeout_ms = int(self.config.get("limits", {}).get("tool_timeout_ms", 3000))
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            self.kernel.invoke,
            "tool.invoke",
            {"tool_id": tool_id, "arguments": arguments},
            context,
        )
        try:
            return future.result(timeout=max(timeout_ms, 1) / 1000).payload
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"tool {tool_id} timed out after {timeout_ms}ms") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _model_tools(self) -> list[dict[str, Any]]:
        assert self.kernel is not None
        tools = self.kernel.invoke("tool.registry.list", {}).payload["tools"]
        result = []
        for tool in tools:
            schema = self.kernel.schema_registry.get(tool["input_schema_ref"]).json_schema
            name = self._safe_tool_name(tool["tool_id"])
            result.append({"tool_id": tool["tool_id"], "function": {"name": name, "description": tool["description"], "parameters": schema}})
        return result

    def _safe_tool_name(self, tool_id: str) -> str:
        return tool_id.replace(".", "__").replace("-", "_")

    def _model_turn(
        self,
        model_messages: list[dict[str, Any]],
        model_tool_payload: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        assert self.kernel is not None
        payload = {
            "system_prompt": self.config.get("system_prompt", ""),
            "messages": model_messages,
            "tools": model_tool_payload,
        }
        if self.kernel.capability_registry.has("model.chat.stream"):
            deltas: list[str] = []
            assistant: dict[str, Any] | None = None
            for event in self.kernel.stream("model.chat.stream", payload, context):
                if event["type"] == "model_delta":
                    delta = event.get("payload", {}).get("delta", "")
                    if delta:
                        deltas.append(delta)
                elif event["type"] == "assistant_message":
                    assistant = event.get("payload", {}).get("message")
            if assistant is None:
                assistant = {"role": "assistant", "content": "".join(deltas), "tool_calls": []}
            return assistant, deltas
        assistant = self.kernel.invoke("model.chat", payload, context).payload["message"]
        return assistant, []

    def _selected_skills(self, user_text: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        assert self.kernel is not None
        if not self.kernel.capability_registry.has("skill.search"):
            return []
        try:
            found = self.kernel.invoke("skill.search", {"query": user_text, "limit": 3}, context).payload["skills"]
        except Exception:
            return []
        selected = []
        for item in found:
            try:
                skill = self.kernel.invoke("skill.get", {"skill_id": item["skill_id"]}, context).payload["skill"]
            except Exception:
                skill = item
            selected.append({**item, "content": skill.get("content", "")})
        return selected

    def _skills_prompt(self, skills: list[dict[str, Any]]) -> str:
        sections = []
        for skill in skills:
            content = skill.get("content") or ""
            sections.append(f"Skill: {skill['skill_id']}\n{content}")
        return "Relevant skills for this task:\n\n" + "\n\n".join(sections)

    def _load_memory(self, user_text: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        assert self.kernel is not None
        limit = self.config.get("limits", {}).get("memory_limit", 5)
        memory = self.kernel.invoke("memory.query", {"query": user_text, "limit": limit}, context).payload["items"]
        if not memory:
            memory = self.kernel.invoke("memory.query", {"query": "", "limit": limit}, context).payload["items"]
        return memory

    def _memory_prompt(self, memory: list[dict[str, Any]]) -> str:
        lines = []
        for item in memory:
            metadata = item.get("metadata") or {}
            kind = metadata.get("kind", "memory")
            lines.append(f"- [{kind}] {item.get('text', '')}")
        return "Relevant memory from previous interactions:\n" + "\n".join(lines)

    def _history_messages(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        history = []
        for message in context.get("history_messages") or []:
            role = message.get("role")
            content = message.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                history.append({"role": role, "content": content})
        limit = self.config.get("limits", {}).get("history_messages", 20)
        return history[-limit:]

    def _maybe_compress_context(
        self,
        transcript: list[dict[str, Any]],
        model_messages: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        assert self.kernel is not None
        limit = self.config.get("limits", {}).get("compress_after_messages", 20)
        if len(transcript) < limit or not self.kernel.capability_registry.has("context.compress"):
            return None
        result = self.kernel.invoke("context.compress", {"messages": transcript}, context).payload
        summary = result.get("summary", "")
        if summary:
            model_messages[:] = [{"role": "system", "content": f"Conversation summary so far: {summary}"}, model_messages[-1]]
        return result

    def _write_memory(self, user_text: str, assistant_text: str, tool_calls: list[dict[str, Any]], context: dict[str, Any]) -> None:
        assert self.kernel is not None
        try:
            self.kernel.invoke("memory.write", {"text": user_text, "metadata": {"kind": "user_message"}}, context)
            if assistant_text:
                self.kernel.invoke("memory.write", {"text": assistant_text, "metadata": {"kind": "assistant_message"}}, context)
            if tool_calls:
                self.kernel.invoke("memory.write", {"text": f"tool_calls: {tool_calls}", "metadata": {"kind": "tool_trace"}}, context)
        except Exception:
            return

    def _final_payload(
        self,
        answer: str,
        stop_reason: str,
        memory: list[dict[str, Any]],
        transcript: list[dict[str, Any]],
        events: list[dict[str, Any]],
        tool_audit: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "answer": answer,
            "tool_calls": tool_calls,
            "memory": memory,
            "transcript": transcript,
            "events": list(events),
            "tool_audit": tool_audit,
            "stop_reason": stop_reason,
        }

    def _normalize_assistant_message(self, message: dict[str, Any], tool_name_to_id: dict[str, str]) -> dict[str, Any]:
        calls = []
        for index, call in enumerate(message.get("tool_calls") or []):
            raw_name = call.get("tool_id") or call.get("name") or ""
            tool_id = tool_name_to_id.get(raw_name, raw_name.replace("__", "."))
            arguments = call.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"_raw": arguments}
            calls.append({"id": call.get("id") or f"call-{index}", "tool_id": tool_id, "arguments": arguments})
        return {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}

    def _to_model_assistant_message(self, message: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
        tool_id_to_name = {tool["tool_id"]: tool["function"]["name"] for tool in tools}
        model_message = {"role": "assistant", "content": message.get("content") or ""}
        if message.get("tool_calls"):
            model_message["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": tool_id_to_name.get(call["tool_id"], self._safe_tool_name(call["tool_id"])), "arguments": json.dumps(call["arguments"], ensure_ascii=False)},
                }
                for call in message["tool_calls"]
            ]
        return model_message
