import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from plugin_agent.http_service import create_app_state


ROOT_DIR = Path(__file__).resolve().parents[2]


class CapturingHandler(BaseHTTPRequestHandler):
    captured = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.__class__.captured.append(
            {
                "method": "POST",
                "path": self.path,
                "headers": dict(self.headers),
                "body": body,
            }
        )
        payload = {"received": json.loads(body), "path": self.path}
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.__class__.captured.append(
            {
                "method": "GET",
                "path": self.path,
                "headers": dict(self.headers),
                "body": "",
            }
        )
        raw = json.dumps({"ok": True, "path": self.path}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):
        pass


def _install_http_tool(state):
    package_dir = ROOT_DIR / "plugin-market" / "http-tool-plugin"
    upload = state.assembly.reserve_upload({"path": str(package_dir)})
    assert upload["plugin_package"]["package_id"] == "tool.http_request"
    state.assembly.install_market_plugin({"package_id": "tool.http_request"})


def test_http_endpoint_request_uses_configured_endpoint_headers_and_body(tmp_path):
    CapturingHandler.captured = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), CapturingHandler)
    try:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
        _install_http_tool(state)

        port = server.server_port
        config = {
            "security": {
                "allowed_schemes": ["http"],
                "allowed_hosts": ["127.0.0.1"],
                "allow_private_networks": True,
            },
            "endpoints": {
                "feishu_notify": {
                    "title": "飞书通知",
                    "method": "POST",
                    "url_template": f"http://127.0.0.1:{port}/messages/{{chat_id}}",
                    "headers": {"Content-Type": "application/json", "X-Fixed": "yes"},
                    "secret_headers": {"Authorization": "Bearer real-secret"},
                    "body_template": {"receive_id": "{chat_id}", "msg_type": "text", "content": {"text": "{text}"}},
                    "allow_extra_headers": True,
                    "allowed_extra_header_names": ["X-Request-ID"],
                }
            },
        }
        kernel = state.assembly.build_kernel(["tool.runtime", "tool.http_request"], configs={"tool.http_request": config})

        registry = kernel.invoke("tool.registry.list", {}).payload
        tool_ids = {tool["tool_id"] for tool in registry["tools"]}
        assert "http.endpoint_request" in tool_ids
        assert "http.raw_request" not in tool_ids

        response = kernel.invoke(
            "tool.invoke",
            {
                "tool_id": "http.endpoint_request",
                "arguments": {
                    "endpoint_id": "feishu_notify",
                    "params": {"chat_id": "oc_123", "text": "任务完成"},
                    "headers": {"X-Request-ID": "req-1"},
                },
            },
        ).payload

        result = response["result"]
        assert result["ok"] is True
        assert result["status_code"] == 200
        assert result["endpoint_id"] == "feishu_notify"
        assert result["body_json"]["received"]["content"]["text"] == "任务完成"

        captured = CapturingHandler.captured[-1]
        captured_headers = {key.lower(): value for key, value in captured["headers"].items()}
        assert captured["path"] == "/messages/oc_123"
        assert captured_headers["authorization"] == "Bearer real-secret"
        assert captured_headers["x-fixed"] == "yes"
        assert captured_headers["x-request-id"] == "req-1"
        assert json.loads(captured["body"]) == {
            "receive_id": "oc_123",
            "msg_type": "text",
            "content": {"text": "任务完成"},
        }
    finally:
        server.shutdown()
        server.server_close()


def test_http_raw_request_requires_explicit_enablement_and_rejects_sensitive_call_headers(tmp_path):
    CapturingHandler.captured = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), CapturingHandler)
    try:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
        _install_http_tool(state)

        port = server.server_port
        config = {
            "security": {
                "allow_raw_requests": True,
                "allowed_schemes": ["http"],
                "allowed_hosts": ["127.0.0.1"],
                "allow_private_networks": True,
            },
        }
        kernel = state.assembly.build_kernel(["tool.runtime", "tool.http_request"], configs={"tool.http_request": config})
        registry = kernel.invoke("tool.registry.list", {}).payload
        assert "http.raw_request" in {tool["tool_id"] for tool in registry["tools"]}

        forbidden = kernel.invoke(
            "tool.invoke",
            {
                "tool_id": "http.raw_request",
                "arguments": {
                    "method": "GET",
                    "url": f"http://127.0.0.1:{port}/raw",
                    "headers": {"Authorization": "Bearer model-secret"},
                },
            },
        ).payload["result"]
        assert forbidden["ok"] is False
        assert forbidden["error"]["code"] == "header_not_allowed"

        allowed = kernel.invoke(
            "tool.invoke",
            {
                "tool_id": "http.raw_request",
                "arguments": {
                    "method": "GET",
                    "url": f"http://127.0.0.1:{port}/raw",
                    "query": {"q": "hello"},
                    "headers": {"X-Trace-ID": "trace-1"},
                },
            },
        ).payload["result"]
        assert allowed["ok"] is True
        assert allowed["body_json"]["path"] == "/raw?q=hello"
        captured_headers = {key.lower(): value for key, value in CapturingHandler.captured[-1]["headers"].items()}
        assert captured_headers["x-trace-id"] == "trace-1"
    finally:
        server.shutdown()
        server.server_close()
