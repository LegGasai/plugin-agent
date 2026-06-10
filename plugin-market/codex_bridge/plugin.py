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


class CodexBridgeAgentLoopPlugin(Plugin):
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
        command = str(self.config.get("command") or "codex").strip()
        resolved = shutil.which(command) if not Path(command).is_absolute() else command
        if not resolved:
            raise ValueError(f"codex command is not available: {command}")
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
        raise RuntimeError("codex bridge stream ended without a completion event")

    def stream(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> Iterator[dict[str, Any]]:
        if capability != "agent.stream":
            yield from super().stream(capability, payload, context)
            return
        prompt = str(payload["message"])
        run_id = context.get("run_id") or f"run-{int(time.time() * 1000)}"
        sequence = 0
        events: list[dict[str, Any]] = []
        transcript: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        tool_calls: list[dict[str, Any]] = []
        tool_audit: list[dict[str, Any]] = []
        raw_events: list[dict[str, Any]] = []
        stderr_lines: list[str] = []
        answer_parts: list[str] = []
        completed = False

        def emit(event_type: str, event_payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal sequence
            event = {"type": event_type, "sequence": sequence, "run_id": run_id, "payload": event_payload}
            sequence += 1
            events.append(event)
            return event

        yield emit("run_started", {"message": prompt, "bridge": "codex"})

        try:
            for source, line in self._run_codex(prompt):
                if source == "stderr":
                    stderr_lines.append(line)
                    continue
                parsed = self._parse_json_line(line)
                if parsed is None:
                    stderr_lines.append(line)
                    continue
                raw_events.append(parsed)
                for event in self._map_codex_event(parsed, answer_parts, transcript, tool_calls, tool_audit):
                    yield emit(event["type"], event["payload"])
                if parsed.get("type") == "turn.completed":
                    completed = True
        except TimeoutError as exc:
            failure = self._final_payload(str(exc), "error", transcript, events, tool_calls, tool_audit, raw_events, stderr_lines)
            yield emit("run_failed", failure)
            return
        except Exception as exc:
            failure = self._final_payload(str(exc), "error", transcript, events, tool_calls, tool_audit, raw_events, stderr_lines)
            yield emit("run_failed", failure)
            return

        answer = "".join(answer_parts).strip()
        if completed:
            final = self._final_payload(answer, "final", transcript, events, tool_calls, tool_audit, raw_events, stderr_lines)
            yield emit("run_completed", final)
            return
        failure = self._final_payload(answer or "\n".join(stderr_lines) or "codex exited without completion", "error", transcript, events, tool_calls, tool_audit, raw_events, stderr_lines)
        yield emit("run_failed", failure)

    def _run_codex(self, prompt: str) -> Iterator[tuple[str, str]]:
        assert self.workspace_root is not None
        command = self._command()
        env = {**os.environ, **{str(key): str(value) for key, value in self.config.get("env", {}).items()}}
        process = subprocess.Popen(
            command,
            cwd=str(self.workspace_root),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        lines: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self._start_reader(process.stdout, "stdout", lines)
        self._start_reader(process.stderr, "stderr", lines)
        assert process.stdin is not None
        process.stdin.write(prompt)
        process.stdin.close()

        timeout_ms = int(self.config.get("timeout_ms", 600000))
        deadline = time.monotonic() + max(timeout_ms, 1) / 1000
        active_readers = 2
        while active_readers:
            if time.monotonic() > deadline:
                process.kill()
                raise TimeoutError(f"codex command timed out after {timeout_ms}ms")
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
            raise RuntimeError(f"codex command exited with code {exit_code}")

    def _command(self) -> list[str]:
        command = [self.command_path, "exec", "--json"]
        if self.config.get("skip_git_repo_check", True):
            command.append("--skip-git-repo-check")
        if self.config.get("bypass_approvals_and_sandbox", False):
            command.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            sandbox = str(self.config.get("sandbox") or "").strip()
            if sandbox:
                command.extend(["--sandbox", sandbox])
        model = str(self.config.get("model") or "").strip()
        if model:
            command.extend(["--model", model])
        profile = str(self.config.get("profile") or "").strip()
        if profile:
            command.extend(["--profile", profile])
        assert self.workspace_root is not None
        command.extend(["--cd", str(self.workspace_root)])
        if self.config.get("ephemeral", True):
            command.append("--ephemeral")
        if self.config.get("ignore_rules", False):
            command.append("--ignore-rules")
        command.extend(str(item) for item in self.config.get("extra_args", []))
        command.append("-")
        return command

    def _map_codex_event(
        self,
        item: dict[str, Any],
        answer_parts: list[str],
        transcript: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        tool_audit: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        event_type = item.get("type")
        body = item.get("item") or {}
        if event_type == "item.started" and body.get("type") == "command_execution":
            return [{"type": "tool_call_started", "payload": {"tool_call_id": body.get("id", ""), "tool_name": "codex.command", "input": {"command": body.get("command", "")}}}]
        if event_type == "item.completed" and body.get("type") == "command_execution":
            ok = body.get("exit_code") in (0, None)
            result = {"command": body.get("command", ""), "output": body.get("aggregated_output", ""), "exit_code": body.get("exit_code")}
            audit = {"tool_call_id": body.get("id", ""), "tool_name": "codex.command", "input": {"command": body.get("command", "")}, "ok": ok, "content": result, "error": None if ok else result}
            tool_audit.append(audit)
            tool_calls.append({"tool_call_id": body.get("id", ""), "tool_id": "codex.command", "arguments": {"command": body.get("command", "")}, "result": result})
            return [{"type": "tool_call_completed", "payload": {"tool_call_id": body.get("id", ""), "tool_name": "codex.command", "result": result, "ok": ok, "error": None if ok else result}}]
        if event_type == "item.completed" and body.get("type") == "agent_message":
            text = str(body.get("text") or "")
            if text:
                answer_parts.append(text)
                transcript.append({"role": "assistant", "content": text})
                return [{"type": "model_delta", "payload": {"delta": text, "source": "codex"}}]
        return []

    def _final_payload(
        self,
        answer: str,
        stop_reason: str,
        transcript: list[dict[str, Any]],
        events: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        tool_audit: list[dict[str, Any]],
        raw_events: list[dict[str, Any]],
        stderr_lines: list[str],
    ) -> dict[str, Any]:
        return {
            "answer": answer,
            "tool_calls": tool_calls,
            "memory": [],
            "transcript": transcript,
            "events": list(events),
            "tool_audit": [
                *tool_audit,
                {"tool_name": "codex.bridge", "ok": stop_reason != "error", "content": {"raw_events": raw_events[-100:], "stderr": self._truncate("\n".join(stderr_lines))}, "error": None if stop_reason != "error" else {"message": answer}},
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
