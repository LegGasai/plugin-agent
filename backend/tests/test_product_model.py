import json
import urllib.error
import urllib.request

from plugin_agent.http_service import PluginAgentHTTPServer, create_app_state
from plugin_agent.assembly import collect_encrypted_paths, deep_merge, redact_config


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


def test_plugin_packages_and_agent_instances_are_persisted_in_sqlite(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        packages = request_json(base, "GET", "/api/plugin-packages")["plugin_packages"]
        assert any(package["package_id"] == "agent.loop.react" for package in packages)
        assert any(package["package_id"] == "model.openrouter" for package in packages)
        assert any(package["package_id"] == "model.deepseek" for package in packages)
        assert any(resource["kind"] == "agent_loop" for package in packages for resource in package["resources"])
        assert sum(1 for package in packages for resource in package["resources"] if resource["kind"] == "model") >= 3
        readable_names = {package["package_id"]: package["name"] for package in packages}
        assert readable_names == {
            "agent.loop.react": "ReAct 智能体循环",
            "context.compressor.summary": "上下文摘要压缩",
            "context.manager": "上下文管理器",
            "mcp.bridge": "MCP 桥接器",
            "memory.file": "文件记忆",
            "model.deepseek": "DeepSeek 模型",
            "model.openai_compatible": "OpenAI 兼容模型",
            "model.openrouter": "OpenRouter 模型",
            "skill.registry": "技能注册表",
            "tool.basic": "基础工具集",
            "tool.runtime": "工具运行时",
        }
        assert all(package["description"] and package["description"] != package["package_id"] for package in packages)
        model_package = next(package for package in packages if package["package_id"] == "model.openai_compatible")
        assert model_package["config_schema_ref"] == "schema://model.openai_compatible.config.v1"
        config_schema = next(schema for schema in model_package["schemas"] if schema["schema_ref"] == model_package["config_schema_ref"])
        assert config_schema["json_schema"]["properties"]["api_key"]["x-encrypted"] is True

        created = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Product Agent",
                "description": "Uses plugin instances",
                "plugin_instances": [
                    {"package_id": "memory.file", "display_name": "Private Memory", "config": {"path": str(tmp_path / "agent-memory.jsonl")}},
                    {"package_id": "skill.registry"},
                    {"package_id": "model.openai_compatible", "config": {"api_key": "secret-key", "model": "local-model"}},
                    {"package_id": "tool.runtime"},
                    {"package_id": "tool.basic"},
                    {"package_id": "agent.loop.react"},
                ],
            },
        )["agent"]

        assert created["id"]
        assert created["description"] == "Uses plugin instances"
        assert created["entry_loop_instance_id"]
        assert len(created["plugin_instances"]) == 6
        model_instance = next(instance for instance in created["plugin_instances"] if instance["package_id"] == "model.openai_compatible")
        assert model_instance["config"]["api_key"] == "********"
        assert model_instance["config"]["model"] == "local-model"
    finally:
        server.stop()

    restarted_state = create_app_state(runtime_dir=tmp_path)
    assert restarted_state.assembly.list_agents()[0]["name"] == "Product Agent"


def test_agent_scoped_capabilities_resources_and_instance_config_restart(tmp_path):
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
                "name": "Scoped Agent",
                "plugin_ids": ["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "agent.loop.react"],
                "configs": {"model.openai_compatible": {"api_key": "secret-key", "model": "first-model"}},
            },
        )["agent"]

        capabilities = request_json(base, "GET", f"/api/agents/{created['id']}/capabilities")["capabilities"]
        assert any(capability["name"] == "agent.run" and capability["provider_instance_id"] for capability in capabilities)

        resources = request_json(base, "GET", f"/api/agents/{created['id']}/resources")["resources"]
        assert any(resource["kind"] == "tool" and resource["resource_id"] == "math.add" for resource in resources)

        model_instance = next(instance for instance in created["plugin_instances"] if instance["package_id"] == "model.openai_compatible")
        updated = request_json(
            base,
            "PUT",
            f"/api/plugin-instances/{model_instance['instance_id']}/config",
            {"config": {"api_key": "new-secret", "model": "second-model"}},
        )["plugin_instance"]
        assert updated["config"]["api_key"] == "********"
        assert updated["config"]["model"] == "second-model"

        restarted = request_json(base, "POST", f"/api/plugin-instances/{model_instance['instance_id']}/restart")["plugin_instance"]
        assert restarted["generation"] == model_instance["generation"] + 1
    finally:
        server.stop()


def test_redacted_secret_placeholder_does_not_overwrite_real_secret(tmp_path):
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
                "name": "Secret Agent",
                "plugin_ids": ["model.openai_compatible"],
                "configs": {"model.openai_compatible": {"api_key": "real-secret", "model": "first-model"}},
            },
        )["agent"]
        model_instance = created["plugin_instances"][0]

        updated = request_json(
            base,
            "PUT",
            f"/api/plugin-instances/{model_instance['instance_id']}/config",
            {"config": {"api_key": "********", "model": "second-model"}},
        )["plugin_instance"]

        assert updated["config"]["api_key"] == "********"
        assert updated["config"]["model"] == "second-model"
        stored = state.assembly.store.get_instance(model_instance["instance_id"])
        hydrated = state.assembly._hydrate_config(stored["config"], stored["secret_refs"])
        assert hydrated["api_key"] == "real-secret"
        assert hydrated["model"] == "second-model"
    finally:
        server.stop()


def test_agent_update_can_replace_plugin_instances_and_preserve_existing_config(tmp_path):
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
                "name": "Editable Agent",
                "plugin_instances": [
                    {"package_id": "memory.file", "config": {"path": str(tmp_path / "editable-memory.jsonl")}},
                    {"package_id": "model.openai_compatible", "config": {"api_key": "real-secret", "model": "first-model"}},
                    {"package_id": "agent.loop.react"},
                ],
            },
        )["agent"]
        model_instance = next(instance for instance in created["plugin_instances"] if instance["package_id"] == "model.openai_compatible")

        updated = request_json(
            base,
            "PUT",
            f"/api/agents/{created['id']}",
            {
                "name": "Edited Agent",
                "description": "Updated from the square",
                "plugin_instances": [
                    {
                        "instance_id": model_instance["instance_id"],
                        "package_id": "model.openai_compatible",
                        "package_version": model_instance["package_version"],
                        "display_name": model_instance["display_name"],
                        "config": {"api_key": "********", "model": "second-model"},
                    },
                    {"package_id": "tool.runtime"},
                    {"package_id": "agent.loop.react"},
                ],
            },
        )["agent"]

        assert updated["name"] == "Edited Agent"
        assert updated["description"] == "Updated from the square"
        assert updated["plugin_ids"] == ["model.openai_compatible", "tool.runtime", "agent.loop.react"]
        updated_model = next(instance for instance in updated["plugin_instances"] if instance["package_id"] == "model.openai_compatible")
        assert updated_model["instance_id"] == model_instance["instance_id"]
        assert updated_model["config"]["api_key"] == "********"
        assert updated_model["config"]["model"] == "second-model"

        stored = state.assembly.store.get_instance(model_instance["instance_id"])
        hydrated = state.assembly._hydrate_config(stored["config"], stored["secret_refs"])
        assert hydrated["api_key"] == "real-secret"
        assert hydrated["model"] == "second-model"
    finally:
        server.stop()


def test_agent_sessions_and_messages_are_persisted(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        created = request_json(base, "POST", "/api/agents", {"name": "Session Agent", "plugin_ids": ["memory.file", "tool.runtime", "agent.loop.react"]})["agent"]

        session = request_json(base, "POST", f"/api/agents/{created['id']}/sessions", {"title": "调试会话"})["session"]
        assert session["agent_id"] == created["id"]
        assert session["title"] == "调试会话"

        sessions = request_json(base, "GET", f"/api/agents/{created['id']}/sessions")["sessions"]
        assert [item["id"] for item in sessions] == [session["id"]]

        state.assembly.store.append_session_message(session["id"], "user", "记住 key 123987")
        messages = request_json(base, "GET", f"/api/sessions/{session['id']}/messages")["messages"]
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "记住 key 123987"

        deleted = request_json(base, "DELETE", f"/api/sessions/{session['id']}")
        assert deleted["deleted"] is True
        sessions = request_json(base, "GET", f"/api/agents/{created['id']}/sessions")["sessions"]
        assert sessions == []
    finally:
        server.stop()


def test_agent_can_be_deleted_with_plugin_instances(tmp_path):
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
                "name": "Disposable Agent",
                "plugin_ids": ["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "agent.loop.react"],
            },
        )["agent"]

        deleted = request_json(base, "DELETE", f"/api/agents/{created['id']}")
        assert deleted == {"deleted": True, "agent_id": created["id"]}
        assert request_json(base, "GET", "/api/agents")["agents"] == []
        assert state.assembly.store.list_instances(created["id"]) == []

        try:
            request_json(base, "GET", f"/api/agents/{created['id']}")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("deleted agent should not be fetchable")
    finally:
        server.stop()


def test_agent_runtime_reports_provider_conflicts_and_explicit_bindings(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        def instances(prefix):
            return [
                {"package_id": "memory.file", "instance_id": f"{prefix}-memory", "config": {"path": str(tmp_path / f"{prefix}-memory.jsonl")}},
                {"package_id": "skill.registry", "instance_id": f"{prefix}-skills"},
                {"package_id": "model.openrouter", "instance_id": f"{prefix}-openrouter", "config": {"api_key": "test-key"}},
                {"package_id": "model.deepseek", "instance_id": f"{prefix}-deepseek", "config": {"api_key": "test-key"}},
                {"package_id": "tool.runtime", "instance_id": f"{prefix}-tool-runtime"},
                {"package_id": "tool.basic", "instance_id": f"{prefix}-tools"},
                {"package_id": "agent.loop.react", "instance_id": f"{prefix}-loop"},
            ]

        conflicted = request_json(
            base,
            "POST",
            "/api/agents",
            {"name": "Conflicted Agent", "plugin_instances": instances("conflicted")},
        )["agent"]

        conflicted_runtime = request_json(base, "GET", f"/api/agents/{conflicted['id']}/runtime")
        assert conflicted_runtime["status"] == "failed"
        assert any(diagnostic["code"] == "provider_conflict" and diagnostic["capability"] == "model.chat" for diagnostic in conflicted_runtime["diagnostics"])

        candidates = request_json(base, "GET", f"/api/agents/{conflicted['id']}/capability-candidates")["capabilities"]
        model_chat = next(item for item in candidates if item["capability"] == "model.chat")
        assert model_chat["status"] == "conflict"
        assert {candidate["provider_instance_id"] for candidate in model_chat["candidates"]} == {
            "conflicted-openrouter",
            "conflicted-deepseek",
        }

        rebound = request_json(
            base,
            "PUT",
            f"/api/agents/{conflicted['id']}/capability-bindings",
            {"capability_bindings": {"model.chat": "conflicted-deepseek"}},
        )["agent"]
        assert rebound["capability_bindings"] == {"model.chat": "conflicted-deepseek"}

        rebound_runtime = request_json(base, "GET", f"/api/agents/{conflicted['id']}/runtime")
        assert rebound_runtime["status"] == "ready"
        rebound_model_chat = next(capability for capability in rebound_runtime["capabilities"] if capability["name"] == "model.chat")
        assert rebound_model_chat["provider_instance_id"] == "conflicted-deepseek"

        bound = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Bound Agent",
                "plugin_instances": instances("bound"),
                "capability_bindings": {"model.chat": "bound-deepseek"},
            },
        )["agent"]
        assert bound["capability_bindings"] == {"model.chat": "bound-deepseek"}

        bound_runtime = request_json(base, "GET", f"/api/agents/{bound['id']}/runtime")
        assert bound_runtime["status"] == "ready"
        model_chat = next(capability for capability in bound_runtime["capabilities"] if capability["name"] == "model.chat")
        assert model_chat["provider_instance_id"] == "bound-deepseek"
        assert bound_runtime["capability_bindings"] == {"model.chat": "bound-deepseek"}
        assert "bound-loop" in bound_runtime["startup_order"]
    finally:
        server.stop()


def test_agent_runtime_reports_model_provider_missing_required_config(tmp_path):
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
                "name": "Unconfigured Model Agent",
                "plugin_ids": ["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "agent.loop.react"],
            },
        )["agent"]

        runtime = request_json(base, "GET", f"/api/agents/{created['id']}/runtime")

        assert runtime["status"] == "failed"
        assert any(
            diagnostic["code"] == "plugin_start_failed"
            and diagnostic["plugin_id"] == "model.openai_compatible"
            and "api_key" in diagnostic["message"]
            for diagnostic in runtime["diagnostics"]
        )
    finally:
        server.stop()


def test_context_manager_dependency_and_hot_restart_are_visible(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        missing = request_json(
            base,
            "POST",
            "/api/agents",
            {"name": "Missing Context Provider", "plugin_ids": ["context.manager"]},
        )["agent"]
        missing_runtime = request_json(base, "GET", f"/api/agents/{missing['id']}/runtime")
        assert missing_runtime["status"] == "failed"
        assert any(
            diagnostic["code"] == "missing_dependency"
            and diagnostic["plugin_id"] == "context.manager"
            and diagnostic["capability"] == "context.compressor.compress"
            for diagnostic in missing_runtime["diagnostics"]
        )

        composed = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Composable Context Agent",
                "plugin_instances": [
                    {"package_id": "context.compressor.summary", "instance_id": "summary-compressor"},
                    {"package_id": "context.manager", "instance_id": "context-manager"},
                ],
            },
        )["agent"]
        runtime = request_json(base, "GET", f"/api/agents/{composed['id']}/runtime")
        assert runtime["status"] == "ready"
        assert "summary-compressor" in runtime["startup_order"]
        assert "context-manager" in runtime["startup_order"]

        compressor = next(instance for instance in composed["plugin_instances"] if instance["package_id"] == "context.compressor.summary")
        restarted = request_json(base, "POST", f"/api/plugin-instances/{compressor['instance_id']}/restart")["plugin_instance"]
        assert restarted["generation"] == compressor["generation"] + 1
        runtime = request_json(base, "GET", f"/api/agents/{composed['id']}/runtime")
        assert runtime["status"] == "ready"
    finally:
        server.stop()


def test_encrypted_config_paths_are_declared_by_schema():
    schema = {
        "type": "object",
        "properties": {
            "credential": {"type": "string", "x-encrypted": True},
            "nested": {
                "type": "object",
                "properties": {
                    "token_value": {"type": "string", "x-secret": True},
                    "plain_secret_name": {"type": "string"},
                },
            },
        },
    }

    assert collect_encrypted_paths(schema) == {"credential", "nested.token_value"}


def test_dynamic_secret_config_paths_are_encrypted_redacted_and_preserved(tmp_path):
    state = create_app_state(runtime_dir=tmp_path)
    schema = {
        "type": "object",
        "properties": {
            "endpoints": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "secret_headers": {
                            "type": "object",
                            "additionalProperties": {"type": "string", "x-secret": True},
                        },
                        "headers": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                },
            },
        },
    }
    encrypted_paths = collect_encrypted_paths(schema)
    config = {
        "endpoints": {
            "notify": {
                "headers": {"Content-Type": "application/json"},
                "secret_headers": {"Authorization": "Bearer real-secret"},
            }
        }
    }

    assert encrypted_paths == {"endpoints.*.secret_headers.*"}
    assert redact_config(config, encrypted_paths)["endpoints"]["notify"]["secret_headers"]["Authorization"] == "********"

    stored_config, secret_refs = state.assembly._split_config_secrets(config, encrypted_paths)
    assert stored_config["endpoints"]["notify"]["secret_headers"] == {}
    assert set(secret_refs) == {"endpoints.notify.secret_headers.Authorization"}

    hydrated = state.assembly._hydrate_config(stored_config, secret_refs)
    assert hydrated["endpoints"]["notify"]["secret_headers"]["Authorization"] == "Bearer real-secret"

    sanitized = state.assembly._strip_redacted_secret_placeholders(
        {
            "endpoints": {
                "notify": {
                    "headers": {"Content-Type": "application/json; charset=utf-8"},
                    "secret_headers": {"Authorization": "********"},
                }
            }
        },
        encrypted_paths,
    )
    merged = deep_merge(state.assembly._hydrate_config(stored_config, secret_refs), sanitized)
    assert merged["endpoints"]["notify"]["secret_headers"]["Authorization"] == "Bearer real-secret"


def test_refresh_plugin_packages_removes_stale_builtin_packages(tmp_path):
    from plugin_agent_sdk import PluginPackage, RuntimeSpec

    state = create_app_state(runtime_dir=tmp_path)
    stale = PluginPackage(
        package_id="stale.builtin",
        name="Stale Builtin",
        version="1.0.0",
        runtime=RuntimeSpec(),
        manifest_path="/tmp/stale/manifest.yaml",
        source="builtin",
        description="Removed builtin package.",
    )
    state.assembly.store.upsert_package(stale)

    state.assembly.refresh_plugin_packages()

    packages = state.assembly.list_installed_plugin_packages()
    assert not any(package["package_id"] == "stale.builtin" for package in packages)
