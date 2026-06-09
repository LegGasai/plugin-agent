
from plugin_agent.kernel import build_default_kernel


def test_tool_invoke_calls_builtin_echo_time_and_math():
    kernel = build_default_kernel()

    echo = kernel.invoke("tool.invoke", {"tool_id": "echo", "arguments": {"text": "hi"}}).payload
    now = kernel.invoke("tool.invoke", {"tool_id": "time.now", "arguments": {"timezone": "UTC"}}).payload
    added = kernel.invoke("tool.invoke", {"tool_id": "math.add", "arguments": {"a": 1, "b": 2}}).payload

    assert echo["result"] == "hi"
    assert "current_time" in now["result"]
    assert added["result"] == 3


def test_memory_write_and_query_round_trip():
    kernel = build_default_kernel()

    kernel.invoke("memory.write", {"text": "user is building a plugin agent", "metadata": {"kind": "note"}})
    result = kernel.invoke("memory.query", {"query": "plugin agent", "limit": 3}).payload

    assert result["items"]
    assert result["items"][0]["text"] == "user is building a plugin agent"


def test_default_agent_reports_model_configuration_error_without_api_key():
    kernel = build_default_kernel()

    assert kernel.runtime_status == "failed"
    assert any(
        diagnostic.code == "plugin_start_failed"
        and diagnostic.plugin_id == "model.openai_compatible"
        and "api_key" in diagnostic.message
        for diagnostic in kernel.diagnostics
    )


def test_default_mcp_bridge_does_not_register_demo_tools_without_configured_servers():
    kernel = build_default_kernel()

    mcp_tools = kernel.invoke("mcp.tools.list", {}).payload
    tools = kernel.invoke("tool.registry.list", {}).payload

    assert mcp_tools["tools"] == []
    assert not any(tool["tool_id"].startswith("mcp.") for tool in tools["tools"])


def test_default_plugins_are_loaded_from_plugin_folders_with_manifests():
    kernel = build_default_kernel()

    for plugin in kernel.plugins.values():
        assert plugin.plugin_dir is not None
        assert plugin.manifest_path is not None
        assert plugin.manifest_path.name == "manifest.yaml"
        assert plugin.manifest_path.exists()
        assert plugin.config

    assert kernel.plugins["agent.loop.react"].config["limits"]["max_turns"] == 8
