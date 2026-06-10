from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
from typing import Any

from plugin_agent_sdk import SchemaDefinition
from plugin_agent_sdk import Plugin as PluginBase


class StdioMCPClient:
    def __init__(self, command: str, args: list[str] | None = None, timeout: int = 10, env: dict[str, str] | None = None) -> None:
        process_env = {**os.environ, **(env or {})}
        self.process = subprocess.Popen([command, *(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=process_env)
        self.timeout = timeout
        self._lock = threading.Lock()
        self._next_id = 1
        try:
            self._request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "plugin-agent", "version": "0.1.0"}})
            self._notify("notifications/initialized", {})
        except Exception:
            self.close()
            raise

    def list_tools(self) -> list[dict[str, Any]]:
        return self._request("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            deadline = time.monotonic() + self.timeout
            request_id = self._next_id
            self._next_id += 1
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            while True:
                response = self._read(deadline)
                if response.get("id") != request_id:
                    continue
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response.get("result", {})

    def _write(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        assert self.process.stdin is not None
        self.process.stdin.write(f"Content-Length: {len(data)}\r\n\r\n".encode("utf-8") + data)
        self.process.stdin.flush()

    def _read(self, deadline: float) -> dict[str, Any]:
        assert self.process.stdout is not None
        header = b""
        while b"\r\n\r\n" not in header:
            header += self._read_exact(1, deadline)
        length_line = [line for line in header.decode("utf-8").split("\r\n") if line.lower().startswith("content-length:")][0]
        size = int(length_line.split(":", 1)[1].strip())
        return json.loads(self._read_exact(size, deadline).decode("utf-8"))

    def _read_exact(self, size: int, deadline: float) -> bytes:
        assert self.process.stdout is not None
        chunks = []
        remaining_size = size
        while remaining_size > 0:
            self._wait_for_stdout(deadline)
            chunk = os.read(self.process.stdout.fileno(), remaining_size)
            if not chunk:
                raise RuntimeError("MCP server closed stdout")
            chunks.append(chunk)
            remaining_size -= len(chunk)
        return b"".join(chunks)

    def _wait_for_stdout(self, deadline: float) -> None:
        assert self.process.stdout is not None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"MCP request timed out after {self.timeout}s")
        readable, _, _ = select.select([self.process.stdout], [], [], remaining)
        if not readable:
            raise TimeoutError(f"MCP request timed out after {self.timeout}s")


class MCPBridgePlugin(PluginBase):
    def start(self, kernel):
        super().start(kernel)
        self.clients: dict[str, StdioMCPClient] = {}
        self._tools: list[dict[str, Any]] = []
        for server in self.config.get("servers", []):
            name = server["name"]
            client = StdioMCPClient(server["command"], server.get("args", []), self.config.get("request_timeout_seconds", 10), server.get("env", {}))
            self.clients[name] = client
            for tool in client.list_tools():
                tool_id = f"mcp.{name}.{tool['name']}"
                input_schema_ref = f"schema://{tool_id}.input.v1"
                output_schema_ref = f"schema://{tool_id}.output.v1"
                kernel.schema_registry.register(SchemaDefinition(schema_ref=input_schema_ref, json_schema=tool.get("inputSchema") or {"type": "object", "properties": {}}))
                kernel.schema_registry.register(SchemaDefinition(schema_ref=output_schema_ref, json_schema={"type": "object"}))
                self._tools.append({"tool_id": tool_id, "title": tool["name"], "description": tool.get("description", ""), "input_schema_ref": input_schema_ref, "output_schema_ref": output_schema_ref, "invoke_capability": "mcp.tool.call"})
        self.tool_definitions = self._tools


    def stop(self) -> None:
        for client in getattr(self, "clients", {}).values():
            client.close()
        super().stop()

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability == "mcp.tools.list":
            return {"tools": self._tools}
        if capability == "mcp.tool.call":
            server_name, tool_name = self._resolve_tool(payload["tool_name"], payload.get("server"))
            return {"result": self.clients[server_name].call_tool(tool_name, payload.get("arguments", {}))}
        return super().invoke(capability, payload, context)

    def _resolve_tool(self, tool_name: str, server: str | None) -> tuple[str, str]:
        if server:
            return server, tool_name
        if tool_name.startswith("mcp."):
            _, server_name, raw_tool_name = tool_name.split(".", 2)
            return server_name, raw_tool_name
        if len(self.clients) == 1:
            return next(iter(self.clients)), tool_name
        raise ValueError("server must be provided when multiple MCP servers are configured")
