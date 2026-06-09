from __future__ import annotations

from email import policy
from email.parser import BytesParser
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from plugin_agent.assembly import AgentAssemblyService
from plugin_agent.kernel import KernelInvokeError


class AppState:
    def __init__(self, runtime_dir: str | Path | None = None, market_dir: str | Path | None = None) -> None:
        self.assembly = AgentAssemblyService(runtime_dir=runtime_dir, market_dir=market_dir)


def create_app_state(runtime_dir: str | Path | None = None, market_dir: str | Path | None = None) -> AppState:
    return AppState(runtime_dir=runtime_dir, market_dir=market_dir)


class PluginAgentRequestHandler(BaseHTTPRequestHandler):
    server: "PluginAgentHTTPServerImpl"

    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)
        try:
            if path == "/api/health":
                self._send_json({"status": "ok"})
            elif path == "/api/installed-plugin-packages":
                tag = query.get("tag", [None])[0]
                self._send_json({"plugin_packages": self.server.state.assembly.list_installed_plugin_packages(tag=tag)})
            elif path == "/api/plugin-packages":
                tag = query.get("tag", [None])[0]
                self._send_json({"plugin_packages": self.server.state.assembly.list_plugin_packages(tag=tag)})
            elif path == "/api/plugins":
                self._send_json({"plugins": self.server.state.assembly.list_plugin_catalog()})
            elif path == "/api/marketplace/plugins":
                tag = query.get("tag", [None])[0]
                self._send_json(self.server.state.assembly.marketplace(tag=tag))
            elif path == "/api/agents":
                self._send_json({"agents": self.server.state.assembly.list_agents()})
            elif path.endswith("/sessions") and path.startswith("/api/agents/"):
                agent_id = unquote(path[len("/api/agents/") : -len("/sessions")])
                self._send_json({"sessions": self.server.state.assembly.list_sessions(agent_id)})
            elif path.endswith("/messages") and path.startswith("/api/sessions/"):
                session_id = unquote(path[len("/api/sessions/") : -len("/messages")])
                self._send_json({"messages": self.server.state.assembly.list_session_messages(session_id)})
            elif path.startswith("/api/sessions/"):
                session_id = unquote(path.removeprefix("/api/sessions/"))
                self._send_json({"session": self.server.state.assembly.get_session(session_id)})
            elif path.endswith("/capabilities") and path.startswith("/api/agents/"):
                agent_id = unquote(path[len("/api/agents/") : -len("/capabilities")])
                self._send_json({"capabilities": self.server.state.assembly.agent_capabilities(agent_id)})
            elif path.endswith("/capability-candidates") and path.startswith("/api/agents/"):
                agent_id = unquote(path[len("/api/agents/") : -len("/capability-candidates")])
                self._send_json({"capabilities": self.server.state.assembly.agent_capability_candidates(agent_id)})
            elif path.endswith("/resources") and path.startswith("/api/agents/"):
                agent_id = unquote(path[len("/api/agents/") : -len("/resources")])
                self._send_json({"resources": self.server.state.assembly.agent_resources(agent_id)})
            elif path.endswith("/runtime") and path.startswith("/api/agents/"):
                agent_id = unquote(path[len("/api/agents/") : -len("/runtime")])
                self._send_json(self.server.state.assembly.agent_runtime(agent_id))
            elif path.startswith("/api/agents/"):
                agent_id = unquote(path.removeprefix("/api/agents/"))
                self._send_json({"agent": self.server.state.assembly.get_agent(agent_id)})
            elif path == "/api/capabilities":
                assembly = self.server.state.assembly.assemble()
                self._send_json({"capabilities": assembly["capabilities"]})
            elif path == "/api/tools":
                assembly = self.server.state.assembly.assemble()
                self._send_json({"tools": assembly["tools"]})
            else:
                self._send_error(404, "not found")
        except KeyError as exc:
            self._send_error(404, str(exc))
        except KernelInvokeError as exc:
            self._send_json({"error": exc.error["message"], "error_detail": exc.error}, status=500)
        except Exception as exc:
            self._send_error(500, str(exc))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/marketplace/upload":
                if self._is_multipart_request():
                    with tempfile.TemporaryDirectory(prefix="plugin-agent-upload-") as temp_dir:
                        upload_path = self._write_multipart_upload(Path(temp_dir))
                        self._send_json(self.server.state.assembly.reserve_upload({"path": str(upload_path)}))
                    return
                payload = self._read_json()
                self._send_json(self.server.state.assembly.reserve_upload(payload))
                return
            payload = self._read_json()
            if path == "/api/marketplace/install":
                self._send_json(self.server.state.assembly.install_market_plugin(payload))
            elif path == "/api/plugin-packages/refresh":
                self._send_json(self.server.state.assembly.refresh_plugin_packages())
            elif path == "/api/dev/validate-plugin":
                self._send_json(self.server.state.assembly.validate_plugin(payload))
            elif path == "/api/agents":
                agent = self.server.state.assembly.create_agent(
                    payload["name"],
                    payload.get("plugin_ids"),
                    payload.get("configs"),
                    payload.get("description", ""),
                    payload.get("plugin_instances"),
                    payload.get("capability_bindings"),
                )
                self._send_json({"agent": agent})
            elif path.endswith("/sessions") and path.startswith("/api/agents/"):
                agent_id = unquote(path[len("/api/agents/") : -len("/sessions")])
                self._send_json({"session": self.server.state.assembly.create_session(agent_id, payload.get("title"))})
            elif path.endswith("/run") and path.startswith("/api/agents/"):
                agent_id = unquote(path[len("/api/agents/") : -len("/run")])
                self._send_json(self.server.state.assembly.run_saved_agent(agent_id, payload["message"], payload.get("session_id")))
            elif path.endswith("/restart") and path.startswith("/api/plugin-instances/"):
                instance_id = unquote(path[len("/api/plugin-instances/") : -len("/restart")])
                self._send_json({"plugin_instance": self.server.state.assembly.restart_plugin_instance(instance_id)})
            elif path == "/api/agents/assemble":
                self._send_json(self.server.state.assembly.assemble(payload.get("plugin_ids"), payload.get("configs")))
            elif path == "/api/agents/run":
                self._send_json(self.server.state.assembly.run_agent(payload["message"], payload.get("plugin_ids"), payload.get("configs")))
            elif path == "/api/agents/stream":
                self._send_sse(self.server.state.assembly.stream_agent(payload["message"], payload.get("plugin_ids"), payload.get("configs")))
            elif path.endswith("/stream") and path.startswith("/api/agents/"):
                agent_id = unquote(path[len("/api/agents/") : -len("/stream")])
                self._send_sse(self.server.state.assembly.stream_saved_agent(agent_id, payload["message"], payload.get("session_id")))
            elif path == "/api/invoke":
                kernel = self.server.state.assembly.build_kernel(payload.get("plugin_ids"), payload.get("configs"))
                self._send_json(kernel.invoke(payload["capability"], payload.get("payload", {})).payload)
            else:
                self._send_error(404, "not found")
        except KeyError as exc:
            self._send_error(404, str(exc))
        except KernelInvokeError as exc:
            self._send_json({"error": exc.error["message"], "error_detail": exc.error}, status=500)
        except Exception as exc:
            self._send_error(500, str(exc))

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        payload = self._read_json()
        try:
            prefix = "/api/plugins/"
            suffix = "/config"
            instance_prefix = "/api/plugin-instances/"
            agent_prefix = "/api/agents/"
            if path.endswith("/capability-bindings") and path.startswith(agent_prefix):
                agent_id = unquote(path[len(agent_prefix) : -len("/capability-bindings")])
                agent = self.server.state.assembly.update_agent_capability_bindings(agent_id, payload.get("capability_bindings", {}))
                self._send_json({"agent": agent})
            elif path.startswith(agent_prefix):
                agent_id = unquote(path.removeprefix(agent_prefix))
                agent = self.server.state.assembly.update_agent(
                    agent_id,
                    name=payload.get("name"),
                    description=payload.get("description"),
                )
                self._send_json({"agent": agent})
            elif path.startswith(instance_prefix) and path.endswith(suffix):
                instance_id = unquote(path[len(instance_prefix) : -len(suffix)])
                plugin_instance = self.server.state.assembly.update_plugin_instance_config(instance_id, payload.get("config", {}))
                self._send_json({"plugin_instance": plugin_instance})
            elif path.startswith(prefix) and path.endswith(suffix):
                plugin_id = unquote(path[len(prefix) : -len(suffix)])
                plugin = self.server.state.assembly.update_plugin_config(plugin_id, payload.get("config", {}))
                self._send_json({"plugin": plugin})
            else:
                self._send_error(404, "not found")
        except KeyError as exc:
            self._send_error(404, str(exc))
        except KernelInvokeError as exc:
            self._send_json({"error": exc.error["message"], "error_detail": exc.error}, status=500)
        except Exception as exc:
            self._send_error(500, str(exc))

    def do_DELETE(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)
        try:
            if path.startswith("/api/installed-plugin-packages/"):
                package_id = unquote(path.removeprefix("/api/installed-plugin-packages/"))
                version = query.get("version", [None])[0]
                self._send_json(self.server.state.assembly.uninstall_installed_plugin(package_id, version=version))
            elif path.startswith("/api/sessions/"):
                session_id = unquote(path.removeprefix("/api/sessions/"))
                self._send_json(self.server.state.assembly.delete_session(session_id))
            elif path.startswith("/api/agents/"):
                agent_id = unquote(path.removeprefix("/api/agents/"))
                self._send_json(self.server.state.assembly.delete_agent(agent_id))
            else:
                self._send_error(404, "not found")
        except KeyError as exc:
            self._send_error(404, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _is_multipart_request(self) -> bool:
        return (self.headers.get("Content-Type") or "").lower().startswith("multipart/form-data")

    def _write_multipart_upload(self, temp_dir: Path) -> Path:
        content_type = self.headers.get("Content-Type")
        if not content_type:
            raise ValueError("Content-Type is required")
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw_body
        )
        if not message.is_multipart():
            raise ValueError("multipart/form-data body is required")

        files: list[tuple[str, bytes]] = []
        relative_paths: list[str] = []
        for part in message.iter_parts():
            disposition = part.get_content_disposition()
            if disposition != "form-data":
                continue
            params = dict(part.get_params(header="content-disposition", unquote=True) or [])
            name = params.get("name")
            payload = part.get_payload(decode=True) or b""
            if name == "files":
                filename = params.get("filename") or "plugin-upload"
                files.append((filename, payload))
            elif name == "relative_paths":
                relative_paths.append(payload.decode("utf-8"))
        if not files:
            raise ValueError("plugin package file is required")

        paths = relative_paths if len(relative_paths) == len(files) else [filename for filename, _ in files]
        if len(files) == 1 and "/" not in paths[0].replace("\\", "/"):
            upload_file = temp_dir / self._safe_upload_filename(paths[0])
            upload_file.write_bytes(files[0][1])
            return upload_file

        upload_root = temp_dir / "plugin-directory"
        for index, (_, payload) in enumerate(files):
            relative_path = self._safe_upload_relative_path(paths[index])
            destination = upload_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)

        first_segments = {Path(self._safe_upload_relative_path(path)).parts[0] for path in paths}
        if len(first_segments) == 1:
            candidate = upload_root / next(iter(first_segments))
            if (candidate / "plugin.yaml").exists():
                return candidate
        return upload_root

    def _safe_upload_filename(self, filename: str) -> str:
        safe_name = Path(filename.replace("\\", "/")).name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("invalid upload filename")
        return safe_name

    def _safe_upload_relative_path(self, raw_path: str) -> Path:
        normalized = raw_path.replace("\\", "/").lstrip("/")
        parts = [part for part in normalized.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError(f"invalid upload path: {raw_path}")
        return Path(*parts)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, events) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        try:
            for event in events:
                data = json.dumps(event, ensure_ascii=False)
                self.wfile.write(f"event: {event['type']}\ndata: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
        except BrokenPipeError:
            return
        except Exception as exc:
            error = exc.error if isinstance(exc, KernelInvokeError) else str(exc)
            event = {"type": "run_failed", "sequence": -1, "run_id": "http-stream", "payload": {"error": error}}
            data = json.dumps(event, ensure_ascii=False)
            self.wfile.write(f"event: run_failed\ndata: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
        finally:
            self.close_connection = True

    def _send_error(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def log_message(self, format: str, *args: Any) -> None:
        return


class PluginAgentHTTPServerImpl(ThreadingHTTPServer):
    def __init__(self, address, state: AppState):
        super().__init__(address, PluginAgentRequestHandler)
        self.state = state


class PluginAgentHTTPServer:
    def __init__(self, state: AppState | None = None, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.state = state or create_app_state()
        self.server = PluginAgentHTTPServerImpl((host, port), self.state)
        self.thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
