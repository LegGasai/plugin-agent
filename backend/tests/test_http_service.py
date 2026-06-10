
import json
import urllib.request
from urllib.parse import quote

from plugin_agent.http_service import PluginAgentHTTPServer, create_app_state
from plugin_agent.plugins.model_openai_compatible.plugin import OpenAICompatibleModelPlugin


def request_json(base_url, method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode())


def request_sse(base_url, path, payload):
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        body = response.read().decode()
        return response.headers["Content-Type"], [
            json.loads(chunk.split("data: ", 1)[1])
            for chunk in body.strip().split("\n\n")
            if "data: " in chunk
        ]


class FakeStreamingModelResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def __iter__(self):
        yield (
            "data: "
            + json.dumps({"choices": [{"delta": {"content": self.content}}]}, ensure_ascii=False)
            + "\n\n"
        ).encode()
        yield b"data: [DONE]\n\n"


def patch_streaming_model_response(monkeypatch, responder, captured_messages=None):
    original_urlopen = urllib.request.urlopen

    def fake_urlopen(request, timeout=None, *args, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if url.startswith("https://model.test/"):
            body = json.loads((request.data or b"{}").decode("utf-8"))
            if captured_messages is not None:
                captured_messages.append(body.get("messages", []))
            return FakeStreamingModelResponse(responder(body))
        if timeout is None:
            return original_urlopen(request, *args, **kwargs)
        return original_urlopen(request, timeout=timeout, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_model_api_key_can_come_from_plugin_config(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]}).encode()

    def fake_urlopen(request, timeout):
        captured["auth"] = request.headers["Authorization"]
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    plugin = OpenAICompatibleModelPlugin({"api_key": "config-key", "base_url": "https://example.test/v1"})
    result = plugin.invoke("model.chat", {"messages": [{"role": "user", "content": "hi"}], "tools": []}, {})

    assert captured["auth"] == "Bearer config-key"
    assert result["message"]["content"] == "ok"


def test_http_service_lists_plugins_updates_config_and_assembles_agent(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        plugins = request_json(base, "GET", "/api/plugins")
        assert any(plugin["id"] == "model.openai_compatible" for plugin in plugins["plugins"])
        model_plugin = next(plugin for plugin in plugins["plugins"] if plugin["id"] == "model.openai_compatible")
        assert model_plugin["config"].get("api_key") is None

        updated = request_json(base, "PUT", "/api/plugins/model.openai_compatible/config", {"config": {"api_key": "secret", "model": "local-model"}})
        assert updated["plugin"]["config"]["api_key"] == "********"
        assert updated["plugin"]["config"]["model"] == "local-model"

        assembly = request_json(
            base,
            "POST",
            "/api/agents/assemble",
            {"plugin_ids": ["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "mcp.bridge", "agent.loop.react"]},
        )
        assert assembly["status"] == "ready"
        assert any(cap["name"] == "agent.run" for cap in assembly["capabilities"])
        assert any(tool["tool_id"] == "math.add" for tool in assembly["tools"])
    finally:
        server.stop()



def test_marketplace_exposes_market_plugins_and_upload_capability(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        marketplace = request_json(base, "GET", "/api/marketplace/plugins")
        assert any(package["package_id"] == "agent.loop.react" for package in marketplace["plugin_packages"])
        assert any(package["package_id"] == "context.compressor.summary" for package in marketplace["plugin_packages"])
        assert all(package["source"] == "market" for package in marketplace["plugin_packages"])
        installed = request_json(base, "GET", "/api/installed-plugin-packages")["plugin_packages"]
        assert any(package["package_id"] == "context.compressor.summary" for package in installed)
        assert any(package["package_id"] == "context.manager" for package in installed)
        assert marketplace["upload"]["available"] is True
        assert marketplace["upload"]["implemented"] is True
        assert marketplace["market_dir"]
        assert "installed_plugins_dir" not in marketplace
    finally:
        server.stop()


def test_installed_plugin_packages_expose_tags_and_can_filter_by_tag(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        packages = request_json(base, "GET", "/api/installed-plugin-packages")["plugin_packages"]
        model_package = next(package for package in packages if package["package_id"] == "model.openai_compatible")
        assert "模型" in model_package["tags"]

        filtered = request_json(base, "GET", f"/api/installed-plugin-packages?tag={quote('模型')}")["plugin_packages"]
        assert filtered
        assert all("模型" in package["tags"] for package in filtered)
        assert {package["package_id"] for package in filtered} == {
            "model.deepseek",
            "model.openai_compatible",
            "model.openrouter",
        }

        compat_filtered = request_json(base, "GET", f"/api/plugin-packages?tag={quote('模型')}")["plugin_packages"]
        assert {package["package_id"] for package in compat_filtered} == {package["package_id"] for package in filtered}
    finally:
        server.stop()


def test_agents_can_be_created_listed_and_run_with_selected_plugins(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        created = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Math Agent",
                "plugin_ids": ["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "agent.loop.react"],
                "configs": {"model.openai_compatible": {"api_key": "secret", "model": "local-model"}},
            },
        )["agent"]

        assert created["id"]
        assert created["name"] == "Math Agent"
        assert created["configs"]["model.openai_compatible"]["api_key"] == "********"

        listed = request_json(base, "GET", "/api/agents")["agents"]
        assert listed[0]["id"] == created["id"]

        fetched = request_json(base, "GET", f"/api/agents/{created['id']}")["agent"]
        assert fetched["plugin_ids"] == created["plugin_ids"]
    finally:
        server.stop()


def test_http_service_streams_saved_agent_events(tmp_path, monkeypatch):
    patch_streaming_model_response(monkeypatch, lambda body: "pong")

    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        created = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Streaming Agent",
                "plugin_ids": ["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "agent.loop.react"],
                "configs": {"model.openai_compatible": {"api_key": "secret", "base_url": "https://model.test/v1", "model": "local-model"}},
            },
        )["agent"]

        content_type, events = request_sse(base, f"/api/agents/{created['id']}/stream", {"message": "ping"})

        assert content_type.startswith("text/event-stream")
        assert any(event["type"] == "model_delta" and event["payload"]["delta"] == "pong" for event in events)
        assert events[-1]["type"] == "run_completed"
    finally:
        server.stop()


def test_http_service_streams_saved_agent_with_session_history(tmp_path, monkeypatch):
    captured_messages = []

    def responder(body):
        return "我看到了历史 key 123987" if any("123987" in message.get("content", "") for message in body.get("messages", [])) else "已记录"

    patch_streaming_model_response(monkeypatch, responder, captured_messages)

    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        created = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Session History Agent",
                "plugin_ids": ["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "agent.loop.react"],
                "configs": {"model.openai_compatible": {"api_key": "secret", "base_url": "https://model.test/v1", "model": "local-model"}},
            },
        )["agent"]
        session = request_json(base, "POST", f"/api/agents/{created['id']}/sessions", {})["session"]

        first_type, first_events = request_sse(base, f"/api/agents/{created['id']}/stream", {"session_id": session["id"], "message": "请记住 key 123987"})
        second_type, second_events = request_sse(base, f"/api/agents/{created['id']}/stream", {"session_id": session["id"], "message": "刚才的 key 是多少？"})

        assert first_type.startswith("text/event-stream")
        assert second_type.startswith("text/event-stream")
        assert first_events[-1]["payload"]["session_id"] == session["id"]
        assert second_events[-1]["payload"]["answer"] == "我看到了历史 key 123987"
        assert any(
            message["role"] == "user" and message["content"] == "请记住 key 123987"
            for message in captured_messages[-1]
        )

        messages = request_json(base, "GET", f"/api/sessions/{session['id']}/messages")["messages"]
        assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant"]
    finally:
        server.stop()


def test_http_service_does_not_leak_memory_between_sessions(tmp_path, monkeypatch):
    def responder(body):
        full_context = "\n".join(message.get("content", "") for message in body.get("messages", []))
        return "密码是 123987" if "123987" in full_context else "我不知道密码"

    patch_streaming_model_response(monkeypatch, responder)

    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        created = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Session Isolation Agent",
                "plugin_ids": ["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "agent.loop.react"],
                "configs": {"model.openai_compatible": {"api_key": "secret", "base_url": "https://model.test/v1", "model": "local-model"}},
            },
        )["agent"]
        first = request_json(base, "POST", f"/api/agents/{created['id']}/sessions", {"title": "密码会话"})["session"]
        second = request_json(base, "POST", f"/api/agents/{created['id']}/sessions", {"title": "独立会话"})["session"]

        request_sse(base, f"/api/agents/{created['id']}/stream", {"session_id": first["id"], "message": "请记住密码 123987"})
        _, events = request_sse(base, f"/api/agents/{created['id']}/stream", {"session_id": second["id"], "message": "刚才让我记住什么密码？"})

        assert events[-1]["type"] == "run_completed"
        assert events[-1]["payload"]["answer"] == "我不知道密码"
    finally:
        server.stop()


def test_http_service_streams_adhoc_agent_events(tmp_path, monkeypatch):
    patch_streaming_model_response(monkeypatch, lambda body: "adhoc")

    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        content_type, events = request_sse(
            server.base_url,
            "/api/agents/stream",
            {
                "message": "ping",
                "plugin_ids": ["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "agent.loop.react"],
                "configs": {"model.openai_compatible": {"api_key": "secret", "base_url": "https://model.test/v1", "model": "local-model"}},
            },
        )

        assert content_type.startswith("text/event-stream")
        assert any(event["type"] == "model_delta" and event["payload"]["delta"] == "adhoc" for event in events)
        assert events[-1]["type"] == "run_completed"
    finally:
        server.stop()


def test_agent_name_and_description_can_be_updated(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        created = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Old Agent",
                "description": "Old description",
                "plugin_ids": ["memory.file", "skill.registry", "tool.basic"],
            },
        )["agent"]

        updated = request_json(
            base,
            "PUT",
            f"/api/agents/{created['id']}",
            {"name": "Research Assistant", "description": "Updated description"},
        )["agent"]

        assert updated["id"] == created["id"]
        assert updated["name"] == "Research Assistant"
        assert updated["description"] == "Updated description"

        fetched = request_json(base, "GET", f"/api/agents/{created['id']}")["agent"]
        assert fetched["name"] == "Research Assistant"
        assert fetched["description"] == "Updated description"
    finally:
        server.stop()
