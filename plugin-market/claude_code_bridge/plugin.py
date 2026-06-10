from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from plugin_agent_sdk import Plugin


class ClaudeCodeBridgeAgentLoopPlugin(Plugin):
    def __init__(self, config: dict[str, Any] | None = None, instance_id: str | None = None) -> None:
        super().__init__(config, instance_id=instance_id)
        self.workspace_root: Path | None = None
        self.command_path = ""

    def start(self, kernel: Any) -> None:
        super().start(kernel)
        workspace_root = str(self.config.get("workspace_root") or "").strip()
        if not workspace_root:
            raise ValueError("workspace_root is required")
        root = Path(workspace_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"workspace_root must be an existing directory: {root}")
        command = str(self.config.get("command") or "claude").strip()
        resolved = shutil.which(command) if not Path(command).is_absolute() else command
        if not resolved:
            raise ValueError(f"claude command is not available: {command}")
        self.workspace_root = root
        self.command_path = resolved

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability != "agent.run":
            return super().invoke(capability, payload, context)
        final_payload: dict[str, Any] | None = None
        failed_payload: dict[str, Any] | None = None
        events: list[dict[str, Any]] = []
        for event in self.stream("agent.stream", payload, context):
            events.append(event)
            if event["type"] == "run_completed":
                final_payload = event["payload"]
            elif event["type"] == "run_failed":
                failed_payload = event["payload"]
        if final_payload is not None:
            return {**final_payload, "events": events}
        if failed_payload is not None:
            return {**failed_payload, "events": events}
        raise RuntimeError("claude code bridge stream ended without a completion event")

    def stream(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> Iterator[dict[str, Any]]:
        if capability != "agent.stream":
            yield from super().stream(capability, payload, context)
            return
        prompt = str(payload["message"])
        run_id = context.get("run_id") or f"run-{int(time.time() * 1000)}"
        sequence = 0
        events: list[dict[str, Any]] = []
        transcript: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        raw_events: list[dict[str, Any]] = []
        stderr_lines: list[str] = []
        answer_parts: list[str] = []
        result_payload: dict[str, Any] | None = None

        def emit(event_type: str, event_payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal sequence
            event = {"type": event_type, "sequence": sequence, "run_id": run_id, "payload": event_payload}
            sequence += 1
            events.append(event)
            return event

        yield emit("run_started", {"message": prompt, "bridge": "claude_code"})

        try:
            for source, line in self._run_claude(prompt):
                if source == "stderr":
                    stderr_lines.append(line)
                    continue
                parsed = self._parse_json_line(line)
                if parsed is None:
                    stderr_lines.append(line)
                    continue
                raw_events.append(parsed)
                mapped, maybe_result = self._map_claude_event(parsed, answer_parts)
                if maybe_result is not None:
                    result_payload = maybe_result
                for event in mapped:
                    yield emit(event["type"], event["payload"])
        except TimeoutError as exc:
            failure = self._final_payload(str(exc), "error", transcript, events, raw_events, stderr_lines)
            yield emit("run_failed", failure)
            return
        except Exception as exc:
            failure = self._final_payload(str(exc), "error", transcript, events, raw_events, stderr_lines)
            yield emit("run_failed", failure)
            return

        answer = str((result_payload or {}).get("result") or "".join(answer_parts)).strip()
        if result_payload and not result_payload.get("is_error", False) and result_payload.get("subtype") == "success":
            transcript.append({"role": "assistant", "content": answer})
            final = self._final_payload(answer, "final", transcript, events, raw_events, stderr_lines)
            yield emit("run_completed", final)
            return
        failure = self._final_payload(answer or "\n".join(stderr_lines) or "claude exited without success result", "error", transcript, events, raw_events, stderr_lines)
        yield emit("run_failed", failure)

    def _run_claude(self, prompt: str) -> Iterator[tuple[str, str]]:
        assert self.workspace_root is not None
        command = self._command(prompt)
        env = {**os.environ, **{str(key): str(value) for key, value in self.config.get("env", {}).items()}}
        process = subprocess.Popen(
            command,
            cwd=str(self.workspace_root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        lines: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self._start_reader(process.stdout, "stdout", lines)
        self._start_reader(process.stderr, "stderr", lines)

        timeout_ms = int(self.config.get("timeout_ms", 600000))
        deadline = time.monotonic() + max(timeout_ms, 1) / 1000
        active_readers = 2
        while active_readers:
            if time.monotonic() > deadline:
                process.kill()
                raise TimeoutError(f"claude command timed out after {timeout_ms}ms")
            try:
                source, line = lines.get(timeout=0.05)
            except queue.Empty:
                if process.poll() is not None and lines.empty():
                    continue
                continue
            if line is None:
                active_readers -= 1
                continue
            yield source, line.rstrip("\n")
        exit_code = process.wait(timeout=1)
        if exit_code != 0:
            raise RuntimeError(f"claude command exited with code {exit_code}")

    def _command(self, prompt: str) -> list[str]:
        command = [self.command_path, "-p", "--verbose", "--output-format", "stream-json"]
        if self.config.get("include_partial_messages", True):
            command.append("--include-partial-messages")
        if self.config.get("no_session_persistence", True):
            command.append("--no-session-persistence")
        if self.config.get("bare", False):
            command.append("--bare")
        model = str(self.config.get("model") or "").strip()
        if model:
            command.extend(["--model", model])
        permission_mode = str(self.config.get("permission_mode") or "").strip()
        if permission_mode:
            command.extend(["--permission-mode", permission_mode])
        if self.config.get("dangerously_skip_permissions", False):
            command.append("--dangerously-skip-permissions")
        allowed_tools = self.config.get("allowed_tools", [])
        if allowed_tools:
            command.extend(["--allowedTools", ",".join(str(item) for item in allowed_tools)])
        disallowed_tools = self.config.get("disallowed_tools", [])
        if disallowed_tools:
            command.extend(["--disallowedTools", ",".join(str(item) for item in disallowed_tools)])
        command.extend(str(item) for item in self.config.get("extra_args", []))
        command.append(prompt)
        return command

    def _map_claude_event(self, event: dict[str, Any], answer_parts: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        if event.get("type") == "result":
            return [], event
        if event.get("type") == "stream_event":
            inner = event.get("event") or {}
            if inner.get("type") == "content_block_delta":
                delta = inner.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text = str(delta.get("text") or "")
                    if text:
                        answer_parts.append(text)
                        return [{"type": "model_delta", "payload": {"delta": text, "source": "claude_code"}}], None
            if inner.get("type") == "content_block_start":
                block = inner.get("content_block") or {}
                if block.get("type") == "tool_use":
                    return [{"type": "tool_call_started", "payload": {"tool_call_id": block.get("id", ""), "tool_name": block.get("name", "claude.tool"), "input": block.get("input", {})}}], None
            if inner.get("type") == "content_block_stop":
                return [], None
        return [], None

    def _final_payload(
        self,
        answer: str,
        stop_reason: str,
        transcript: list[dict[str, Any]],
        events: list[dict[str, Any]],
        raw_events: list[dict[str, Any]],
        stderr_lines: list[str],
    ) -> dict[str, Any]:
        return {
            "answer": answer,
            "tool_calls": [],
            "memory": [],
            "transcript": transcript,
            "events": list(events),
            "tool_audit": [
                {"tool_name": "claude_code.bridge", "ok": stop_reason != "error", "content": {"raw_events": raw_events[-100:], "stderr": self._truncate("\n".join(stderr_lines))}, "error": None if stop_reason != "error" else {"message": answer}}
            ],
            "stop_reason": stop_reason,
        }

    def _start_reader(self, stream: Any, source: str, lines: queue.Queue[tuple[str, str | None]]) -> None:
        def read() -> None:
            try:
                for line in iter(stream.readline, ""):
                    lines.put((source, line))
            finally:
                lines.put((source, None))

        threading.Thread(target=read, daemon=True).start()

    def _parse_json_line(self, line: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _truncate(self, text: str) -> str:
        max_bytes = int(self.config.get("max_output_bytes", 1000000))
        raw = text.encode("utf-8")
        if len(raw) <= max_bytes:
            return text
        return raw[:max_bytes].decode("utf-8", errors="replace")
