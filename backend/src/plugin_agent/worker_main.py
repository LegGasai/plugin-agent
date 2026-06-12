from __future__ import annotations

import json
import queue
import sys
import threading
from pathlib import Path
from typing import Any, Iterator

from plugin_agent.plugin_store import load_installed_plugin_class
from plugin_agent.runtime.protocol import HostMethod, PluginMethod, WorkerMethod
from plugin_agent_sdk import InvokeResponse, PluginRuntimeContext, SchemaDefinition, ToolDefinition


class _SchemaBinding:
    def __init__(self, json_schema: dict[str, Any]) -> None:
        self.json_schema = json_schema


class HostSchemaRegistryProxy:
    def __init__(self, client: "WorkerClient", instance_id: str) -> None:
        self.client = client
        self.instance_id = instance_id

    def get(self, schema_ref: str) -> _SchemaBinding:
        result = self.client.request(
            HostMethod.SCHEMA_GET,
            {"caller_instance_id": self.instance_id, "schema_ref": schema_ref},
        )
        return _SchemaBinding(result["json_schema"])

    def validate_payload(self, schema_ref: str | None, payload: dict[str, Any], phase: str) -> None:
        self.client.request(
            HostMethod.SCHEMA_VALIDATE,
            {
                "caller_instance_id": self.instance_id,
                "schema_ref": schema_ref,
                "payload": payload,
                "phase": phase,
            },
        )

    def register(self, schema: SchemaDefinition) -> None:
        self.client.request(
            HostMethod.SCHEMA_REGISTER,
            {"caller_instance_id": self.instance_id, "schema": schema.model_dump()},
        )


class HostCapabilityRegistryProxy:
    def __init__(self, client: "WorkerClient", instance_id: str) -> None:
        self.client = client
        self.instance_id = instance_id

    def has(self, capability: str) -> bool:
        result = self.client.request(
            HostMethod.CAPABILITY_HAS,
            {"caller_instance_id": self.instance_id, "capability": capability},
        )
        return bool(result.get("has"))

_protocol_stdout = sys.stdout
sys.stdout = sys.stderr


class _PendingRequest:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: dict[str, Any] | None = None


class HostKernelProxy:
    def __init__(self, client: "WorkerClient", instance_id: str) -> None:
        self.client = client
        self.instance_id = instance_id
        self.schema_registry = HostSchemaRegistryProxy(client, instance_id)
        self.capability_registry = HostCapabilityRegistryProxy(client, instance_id)

    def invoke(self, capability: str, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> InvokeResponse:
        result = self.client.request(
            HostMethod.INVOKE,
            {
                "caller_instance_id": self.instance_id,
                "capability": capability,
                "payload": payload or {},
                "context": context or {},
            },
        )
        return InvokeResponse.model_validate(result)

    def stream(
        self, capability: str, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        yield from self.client.stream_request(
            HostMethod.STREAM,
            {
                "caller_instance_id": self.instance_id,
                "capability": capability,
                "payload": payload or {},
                "context": context or {},
            },
        )

    def collect_tool_definitions(self) -> list[ToolDefinition]:
        result = self.client.request(
            HostMethod.COLLECT_TOOL_DEFINITIONS,
            {"caller_instance_id": self.instance_id},
        )
        return [ToolDefinition.model_validate(tool) for tool in result]


class WorkerClient:
    def __init__(self) -> None:
        self.instances: dict[str, Any] = {}
        self.lock = threading.Lock()
        self.pending: dict[str, _PendingRequest] = {}
        self.streams: dict[str, queue.Queue[tuple[str, Any]]] = {}
        self._next_id = 0
        self.shutdown = threading.Event()

    def run(self) -> None:
        for line in sys.stdin:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in message and "method" not in message:
                self._handle_response(message)
                continue
            method = message.get("method")
            if method == HostMethod.STREAM_EVENT:
                params = message.get("params") or {}
                stream_queue = self.streams.get(str(params.get("request_id")))
                if stream_queue:
                    stream_queue.put(("event", params.get("event")))
                continue
            if method:
                threading.Thread(target=self._handle_request, args=(message,), daemon=True).start()
            if self.shutdown.is_set():
                break

    def request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        request_id = self._send_request(method, params)
        pending = self.pending[request_id]
        if not pending.event.wait(timeout):
            self.pending.pop(request_id, None)
            raise TimeoutError(f"host request timed out: {method}")
        if pending.error:
            raise RuntimeError(pending.error.get("message") or pending.error.get("code") or "host request failed")
        return pending.result

    def stream_request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Iterator[dict[str, Any]]:
        request_id = self._next_request_id()
        stream_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.streams[request_id] = stream_queue
        self._send_request_with_id(request_id, method, params)
        try:
            while True:
                kind, value = stream_queue.get(timeout=timeout)
                if kind == "event":
                    yield value
                    continue
                if kind == "error":
                    raise RuntimeError(value.get("message") or value.get("code") or "host stream failed")
                return
        finally:
            self.streams.pop(request_id, None)
            self.pending.pop(request_id, None)

    def _send_request(self, method: str, params: dict[str, Any]) -> str:
        request_id = self._next_request_id()
        self._send_request_with_id(request_id, method, params)
        return request_id

    def _next_request_id(self) -> str:
        with self.lock:
            self._next_id += 1
            request_id = f"worker-{self._next_id}"
            self.pending[request_id] = _PendingRequest()
            return request_id

    def _send_request_with_id(self, request_id: str, method: str, params: dict[str, Any]) -> None:
        with self.lock:
            _protocol_stdout.write(
                json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n"
            )
            _protocol_stdout.flush()

    def _send_response(self, request_id: str, result: Any = None, error: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            message["error"] = error
        else:
            message["result"] = result
        with self.lock:
            _protocol_stdout.write(json.dumps(message) + "\n")
            _protocol_stdout.flush()

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        with self.lock:
            _protocol_stdout.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
            _protocol_stdout.flush()

    def _handle_response(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("id"))
        pending = self.pending.get(request_id)
        stream_queue = self.streams.get(request_id)
        if "error" in message:
            if stream_queue:
                stream_queue.put(("error", message["error"]))
            if pending:
                pending.error = message["error"]
                pending.event.set()
            return
        if stream_queue:
            stream_queue.put(("done", message.get("result")))
        if pending:
            pending.result = message.get("result")
            pending.event.set()

    def _handle_request(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("id"))
        method = message.get("method")
        params = message.get("params") or {}
        try:
            if method == PluginMethod.CREATE_INSTANCE:
                self._create_instance(params)
                self._send_response(request_id, {"ok": True})
            elif method == PluginMethod.START:
                plugin = self.instances[params["instance_id"]]
                plugin.start(HostKernelProxy(self, params["instance_id"]))
                self._send_response(request_id, {"ok": True})
            elif method == PluginMethod.AFTER_START_ALL:
                plugin = self.instances[params["instance_id"]]
                plugin.after_start_all(HostKernelProxy(self, params["instance_id"]))
                self._send_response(request_id, {"ok": True})
            elif method == PluginMethod.DESCRIBE:
                plugin = self.instances[params["instance_id"]]
                self._send_response(
                    request_id,
                    {
                        "resources": [
                            resource.model_dump() if hasattr(resource, "model_dump") else resource
                            for resource in getattr(plugin, "resource_specs", [])
                        ],
                        "tool_definitions": [
                            tool.model_dump() if hasattr(tool, "model_dump") else tool
                            for tool in getattr(plugin, "tool_definitions", [])
                        ]
                    },
                )
            elif method == PluginMethod.INVOKE:
                plugin = self.instances[params["instance_id"]]
                self._send_response(
                    request_id,
                    plugin.invoke(params["capability"], params.get("payload") or {}, params.get("context") or {}),
                )
            elif method == PluginMethod.STREAM:
                plugin = self.instances[params["instance_id"]]
                for event in plugin.stream(params["capability"], params.get("payload") or {}, params.get("context") or {}):
                    self._send_notification(PluginMethod.STREAM_EVENT, {"request_id": request_id, "event": event})
                self._send_response(request_id, {"ok": True})
            elif method == PluginMethod.STOP_INSTANCE:
                plugin = self.instances.pop(params["instance_id"], None)
                if plugin is not None:
                    plugin.stop()
                self._send_response(request_id, {"ok": True})
            elif method == WorkerMethod.SHUTDOWN:
                for plugin in list(self.instances.values()):
                    plugin.stop()
                self.instances.clear()
                self.shutdown.set()
                self._send_response(request_id, {"ok": True})
            else:
                self._send_response(request_id, error={"code": "unknown_method", "message": f"unknown method: {method}"})
        except Exception as exc:
            code = "plugin_start_failed" if method == PluginMethod.START else "worker_error"
            self._send_response(request_id, error={"code": code, "message": str(exc)})

    def _create_instance(self, params: dict[str, Any]) -> None:
        installed_path = Path(params["installed_path"]).resolve()
        plugin_class = load_installed_plugin_class(installed_path, params["entrypoint"])
        plugin = plugin_class(params.get("config") or {}, instance_id=params["instance_id"])
        plugin.runtime_context = PluginRuntimeContext.model_validate(params["runtime_context"])
        self.instances[params["instance_id"]] = plugin


def main() -> None:
    WorkerClient().run()


if __name__ == "__main__":
    main()
