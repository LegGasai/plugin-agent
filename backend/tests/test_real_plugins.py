
import signal
import sys
import time
from pathlib import Path

import pytest

from plugin_agent.kernel import AgentKernel, PluginBase
from plugin_agent.plugins.agent_loop_react.plugin import ReactAgentLoopPlugin
from plugin_agent.plugins.mcp_bridge_plugin.plugin import MCPBridgePlugin
from plugin_agent.plugins.memory_file.plugin import FileMemoryPlugin
from plugin_agent.plugins.skill_registry.plugin import SkillRegistryPlugin
from plugin_agent.plugins.tool_basic.plugin import BasicToolPlugin
from plugin_agent.plugins.tool_runtime_plugin.plugin import ToolRuntimePlugin


class ScriptedModelPlugin(PluginBase):
    descriptor = {
        "id": "model.scripted",
        "version": "1.0.0",
        "provides": [
            {
                "name": "model.chat",
                "version": "1.0.0",
                "input_schema_ref": "schema://model.chat.input.v1",
                "output_schema_ref": "schema://model.chat.output.v1",
            }
        ],
    }
    schemas = [
        {
            "schema_ref": "schema://model.chat.input.v1",
            "json_schema": {"type": "object", "required": ["messages", "tools"], "properties": {"messages": {"type": "array"}, "tools": {"type": "array"}, "system_prompt": {"type": "string"}}, "additionalProperties": False},
        },
        {
            "schema_ref": "schema://model.chat.output.v1",
            "json_schema": {"type": "object", "required": ["message"], "properties": {"message": {"type": "object"}, "raw": {}}, "additionalProperties": False},
        },
    ]

    def invoke(self, capability, payload, context):
        messages = payload["messages"]
        if messages[-1]["role"] == "user":
            return {
                "message": {
                    "role": "assistant",
                    "content": "I need math.add.",
                    "tool_calls": [
                        {"id": "call-1", "tool_id": "math.add", "arguments": {"a": 2, "b": 5}}
                    ],
                }
            }
        return {"message": {"role": "assistant", "content": "The answer is 7", "tool_calls": []}}


class ScriptedStreamingModelPlugin(ScriptedModelPlugin):
    descriptor = {
        "id": "model.scripted_streaming",
        "version": "1.0.0",
        "provides": [
            {
                "name": "model.chat",
                "version": "1.0.0",
                "input_schema_ref": "schema://model.chat.input.v1",
                "output_schema_ref": "schema://model.chat.output.v1",
            },
            {
                "name": "model.chat.stream",
                "version": "1.0.0",
                "input_schema_ref": "schema://model.chat.input.v1",
                "output_schema_ref": "schema://model.chat.stream.event.v1",
            },
        ],
    }
    schemas = [
        *ScriptedModelPlugin.schemas,
        {
            "schema_ref": "schema://model.chat.stream.event.v1",
            "json_schema": {
                "type": "object",
                "required": ["type", "sequence", "run_id", "payload"],
                "properties": {
                    "type": {"type": "string"},
                    "sequence": {"type": "integer"},
                    "run_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "additionalProperties": False,
            },
        },
    ]

    def stream(self, capability, payload, context):
        messages = payload["messages"]
        run_id = context["run_id"]
        if messages[-1]["role"] == "user":
            yield {
                "type": "assistant_message",
                "sequence": 0,
                "run_id": run_id,
                "payload": {
                    "message": {
                        "role": "assistant",
                        "content": "I need math.add.",
                        "tool_calls": [{"id": "call-1", "tool_id": "math.add", "arguments": {"a": 2, "b": 5}}],
                    }
                },
            }
            return
        yield {"type": "model_delta", "sequence": 0, "run_id": run_id, "payload": {"delta": "The answer "}}
        yield {"type": "model_delta", "sequence": 1, "run_id": run_id, "payload": {"delta": "is 7"}}
        yield {
            "type": "assistant_message",
            "sequence": 2,
            "run_id": run_id,
            "payload": {"message": {"role": "assistant", "content": "The answer is 7", "tool_calls": []}},
        }


class FailingAfterDeltaStreamingModelPlugin(ScriptedStreamingModelPlugin):
    descriptor = {
        "id": "model.failing_after_delta",
        "version": "1.0.0",
        "provides": ScriptedStreamingModelPlugin.descriptor["provides"],
    }

    def stream(self, capability, payload, context):
        yield {"type": "model_delta", "sequence": 0, "run_id": context["run_id"], "payload": {"delta": "partial"}}
        raise RuntimeError("model stream interrupted")


class RecordingContextCompressorPlugin(PluginBase):
    descriptor = {
        "id": "context.compressor.test",
        "version": "1.0.0",
        "provides": [
            {
                "name": "context.compress",
                "version": "1.0.0",
                "input_schema_ref": "schema://context.compress.input.v1",
                "output_schema_ref": "schema://context.compress.output.v1",
            }
        ],
    }
    schemas = [
        {
            "schema_ref": "schema://context.compress.input.v1",
            "json_schema": {"type": "object", "required": ["messages"], "properties": {"messages": {"type": "array"}}, "additionalProperties": True},
        },
        {
            "schema_ref": "schema://context.compress.output.v1",
            "json_schema": {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}, "additionalProperties": False},
        },
    ]

    def invoke(self, capability, payload, context):
        return {"summary": f"compressed {len(payload['messages'])} messages"}


class MemoryAwareModelPlugin(ScriptedModelPlugin):
    descriptor = {
        "id": "model.memory_aware",
        "version": "1.0.0",
        "provides": ScriptedModelPlugin.descriptor["provides"],
    }

    def invoke(self, capability, payload, context):
        content = "\n".join(str(message.get("content", "")) for message in payload["messages"])
        if "123987" in content:
            answer = "你刚才输入的 key 是 123987"
        else:
            answer = "我没有看到之前的 key"
        return {"message": {"role": "assistant", "content": answer, "tool_calls": []}}


class SlowToolPlugin(PluginBase):
    descriptor = {
        "id": "tool.slow",
        "version": "1.0.0",
        "provides": [
            {
                "name": "tool.slow_wait",
                "version": "1.0.0",
                "input_schema_ref": "schema://tool.slow_wait.input.v1",
                "output_schema_ref": "schema://tool.slow_wait.output.v1",
            }
        ],
    }
    resources = [
        {
            "kind": "tool",
            "id": "slow.wait",
            "title": "Slow Wait",
            "description": "Sleep before returning.",
            "invoke_capability": "tool.slow_wait",
            "schema_refs": {"input": "schema://tool.slow_wait.input.v1", "output": "schema://tool.slow_wait.output.v1"},
        }
    ]
    schemas = [
        {
            "schema_ref": "schema://tool.slow_wait.input.v1",
            "json_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "schema_ref": "schema://tool.slow_wait.output.v1",
            "json_schema": {"type": "object", "required": ["result"], "properties": {"result": {"type": "string"}}, "additionalProperties": False},
        },
    ]

    def invoke(self, capability, payload, context):
        if capability == "tool.slow_wait":
            time.sleep(0.2)
            return {"result": "finished"}
        return super().invoke(capability, payload, context)


class SlowToolCallingModelPlugin(ScriptedModelPlugin):
    descriptor = {
        "id": "model.slow_tool_calling",
        "version": "1.0.0",
        "provides": ScriptedModelPlugin.descriptor["provides"],
    }

    def invoke(self, capability, payload, context):
        if payload["messages"][-1]["role"] == "user":
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call-slow", "tool_id": "slow.wait", "arguments": {}}],
                }
            }
        return {"message": {"role": "assistant", "content": "done", "tool_calls": []}}


def build_scripted_kernel(memory_path: Path | None = None) -> AgentKernel:
    kernel = AgentKernel()
    kernel.load_plugins([
        FileMemoryPlugin({"path": str(memory_path) if memory_path else None}),
        SkillRegistryPlugin(),
        ScriptedModelPlugin(),
        ToolRuntimePlugin(),
        BasicToolPlugin(),
        ReactAgentLoopPlugin(),
    ])
    kernel.start_all()
    return kernel


def build_memory_aware_kernel(memory_path: Path) -> AgentKernel:
    kernel = AgentKernel()
    kernel.load_plugins([
        FileMemoryPlugin({"path": str(memory_path)}),
        MemoryAwareModelPlugin(),
        ToolRuntimePlugin(),
        ReactAgentLoopPlugin(),
    ])
    kernel.start_all()
    return kernel


def build_streaming_kernel(memory_path: Path | None = None, skill_dir: Path | None = None) -> AgentKernel:
    kernel = AgentKernel()
    kernel.load_plugins([
        FileMemoryPlugin({"path": str(memory_path) if memory_path else None}),
        SkillRegistryPlugin({"skill_dirs": [str(skill_dir)]} if skill_dir else None),
        ScriptedStreamingModelPlugin(),
        ToolRuntimePlugin(),
        BasicToolPlugin(),
        RecordingContextCompressorPlugin(),
        ReactAgentLoopPlugin({"limits": {"max_turns": 4, "compress_after_messages": 1}}),
    ])
    kernel.start_all()
    return kernel


def test_react_loop_uses_model_chat_capability_and_tool_observations(tmp_path):
    kernel = build_scripted_kernel(tmp_path / "memory.jsonl")

    result = kernel.invoke("agent.run", {"message": "please add 2+5"}).payload

    assert result["answer"] == "The answer is 7"
    assert result["tool_calls"][0]["tool_id"] == "math.add"
    assert result["tool_audit"][0]["content"] == 7
    assert [message["role"] for message in result["transcript"]] == ["user", "assistant", "tool", "assistant"]
    assert any(event["type"] == "assistant_message" for event in result["events"])


def test_react_loop_streams_model_deltas_tools_and_context_compression(tmp_path):
    skill_dir = tmp_path / "skills"
    helper = skill_dir / "math-helper"
    helper.mkdir(parents=True)
    (helper / "SKILL.md").write_text("---\nname: math-helper\ndescription: Use math.add for arithmetic.\n---\n# Math Helper\nUse math.add.")
    kernel = build_streaming_kernel(tmp_path / "memory.jsonl", skill_dir)

    events = list(kernel.stream("agent.stream", {"message": "please add 2+5"}, {"agent_id": "agent-test"}))

    assert [event["type"] for event in events][0] == "run_started"
    assert any(event["type"] == "skills_selected" and event["payload"]["skills"] == [] for event in events)
    assert any(event["type"] == "tool_call_started" and event["payload"]["tool_name"] == "math.add" for event in events)
    assert any(event["type"] == "tool_call_completed" and event["payload"]["result"] == 7 for event in events)
    assert [event["payload"]["delta"] for event in events if event["type"] == "model_delta"] == ["The answer ", "is 7"]
    assert any(event["type"] == "context_compressed" and event["payload"]["summary"].startswith("compressed") for event in events)
    completed = [event for event in events if event["type"] == "run_completed"][-1]
    assert completed["payload"]["answer"] == "The answer is 7"


def test_react_loop_forwards_model_delta_before_stream_failure(tmp_path):
    kernel = AgentKernel()
    kernel.load_plugins([
        FileMemoryPlugin({"path": str(tmp_path / "memory.jsonl")}),
        SkillRegistryPlugin(),
        FailingAfterDeltaStreamingModelPlugin(),
        ToolRuntimePlugin(),
        ReactAgentLoopPlugin({"limits": {"max_turns": 1}}),
    ])
    kernel.start_all()

    events = list(kernel.stream("agent.stream", {"message": "stream then fail"}, {"agent_id": "agent-test"}))

    event_types = [event["type"] for event in events]
    assert "model_delta" in event_types
    assert event_types.index("model_delta") < event_types.index("run_failed")
    assert [event["payload"]["delta"] for event in events if event["type"] == "model_delta"] == ["partial"]


def test_file_memory_persists_between_plugin_instances(tmp_path):
    memory_path = tmp_path / "memory.jsonl"
    first = build_scripted_kernel(memory_path)
    first.invoke("memory.write", {"text": "persistent plugin memory", "metadata": {"kind": "note"}})

    second = build_scripted_kernel(memory_path)
    result = second.invoke("memory.query", {"query": "plugin memory", "limit": 5}).payload

    assert result["items"][0]["text"] == "persistent plugin memory"


def test_react_loop_injects_recent_memory_into_model_context(tmp_path):
    memory_path = tmp_path / "memory.jsonl"
    first = build_memory_aware_kernel(memory_path)
    first.invoke("agent.run", {"message": "你好，请记住我的key: 123987"}).payload

    second = build_memory_aware_kernel(memory_path)
    result = second.invoke("agent.run", {"message": "我刚才输入的key是多少？"}).payload

    assert result["answer"] == "你刚才输入的 key 是 123987"
    assert any("123987" in item["text"] for item in result["memory"])


def test_react_loop_injects_session_history_into_model_context(tmp_path):
    kernel = build_memory_aware_kernel(tmp_path / "memory.jsonl")

    result = kernel.invoke(
        "agent.run",
        {"message": "我刚才输入的key是多少？"},
        {"history_messages": [{"role": "user", "content": "你好，请记住我的key: 123987"}]},
    ).payload

    assert result["answer"] == "你刚才输入的 key 是 123987"


def test_skill_registry_loads_skill_markdown_files(tmp_path):
    skill_dir = tmp_path / "skills" / "debugger"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: debugger\ndescription: Debug carefully.\n---\n# Debugger\nUse evidence.")

    kernel = AgentKernel()
    kernel.load_plugin(SkillRegistryPlugin({"skill_dirs": [str(tmp_path / "skills")]}))
    kernel.start_all()

    listed = kernel.invoke("skill.list", {}).payload["skills"]

    assert listed[0]["skill_id"] == "debugger"
    assert listed[0]["description"] == "Debug carefully."


def test_skill_registry_exposes_activation_and_file_read_tools(tmp_path):
    skill_dir = tmp_path / "skills" / "debugger"
    refs_dir = skill_dir / "references"
    refs_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: debugger\ndescription: Debug carefully.\n---\n# Debugger\nUse evidence.")
    (refs_dir / "checklist.md").write_text("Collect evidence first.")

    kernel = AgentKernel()
    kernel.load_plugins([SkillRegistryPlugin({"skill_dirs": [str(tmp_path / "skills")]}), ToolRuntimePlugin()])
    kernel.start_all()

    tools = kernel.invoke("tool.registry.list", {}).payload["tools"]
    assert {"activate_skill", "read_skill_file"}.issubset({tool["tool_id"] for tool in tools})

    activated = kernel.invoke("tool.invoke", {"tool_id": "activate_skill", "arguments": {"name": "debugger"}}).payload["result"]
    assert activated["name"] == "debugger"
    assert {"path": "SKILL.md", "type": "file", "size": len((skill_dir / "SKILL.md").read_text())} in activated["files"]
    assert any(entry["path"] == "references/checklist.md" for entry in activated["files"])

    read = kernel.invoke("tool.invoke", {"tool_id": "read_skill_file", "arguments": {"name": "debugger", "path": "references/checklist.md"}}).payload["result"]
    assert read["content"] == "Collect evidence first."


def test_skill_registry_read_skill_file_rejects_path_escape(tmp_path):
    skill_dir = tmp_path / "skills" / "debugger"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: debugger\ndescription: Debug carefully.\n---\n# Debugger")
    (tmp_path / "secret.txt").write_text("secret")

    kernel = AgentKernel()
    kernel.load_plugins([SkillRegistryPlugin({"skill_dirs": [str(tmp_path / "skills")]}), ToolRuntimePlugin()])
    kernel.start_all()

    with pytest.raises(Exception, match="skill file path must stay inside"):
        kernel.invoke("tool.invoke", {"tool_id": "read_skill_file", "arguments": {"name": "debugger", "path": "../secret.txt"}})


def test_mcp_bridge_discovers_and_calls_stdio_tool(tmp_path):
    server = tmp_path / "mcp_server.py"
    server.write_text(r'''
import json
import sys

def read_msg():
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = sys.stdin.buffer.read(1)
        if not chunk:
            return None
        header += chunk
    size = int([line for line in header.decode().split("\r\n") if line.lower().startswith("content-length:")][0].split(":", 1)[1])
    return json.loads(sys.stdin.buffer.read(size).decode())

def write_msg(payload):
    data = json.dumps(payload).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
    sys.stdout.buffer.flush()

while True:
    msg = read_msg()
    if msg is None:
        break
    method = msg.get("method")
    if method == "initialize":
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2024-11-05", "capabilities": {}}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        schema = {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}
        tool = {"name": "echo", "description": "Echo text", "inputSchema": schema}
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [tool]}})
    elif method == "tools/call":
        args = msg["params"]["arguments"]
        result = {"content": [{"type": "text", "text": args["text"]}]}
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": result})
''')

    kernel = AgentKernel()
    kernel.load_plugins([
        ToolRuntimePlugin(),
        MCPBridgePlugin({"servers": [{"name": "local", "command": sys.executable, "args": [str(server)]}]}),
    ])
    kernel.start_all()

    tools = kernel.invoke("tool.registry.list", {}).payload["tools"]
    result = kernel.invoke("tool.invoke", {"tool_id": "mcp.local.echo", "arguments": {"text": "hello"}}).payload

    assert any(tool["tool_id"] == "mcp.local.echo" for tool in tools)
    assert result["result"]["content"][0]["text"] == "hello"


def test_mcp_bridge_passes_configured_environment_to_stdio_server(tmp_path):
    server = tmp_path / "mcp_env_server.py"
    server.write_text(r'''
import json
import os
import sys

def read_msg():
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = sys.stdin.buffer.read(1)
        if not chunk:
            return None
        header += chunk
    size = int([line for line in header.decode().split("\r\n") if line.lower().startswith("content-length:")][0].split(":", 1)[1])
    return json.loads(sys.stdin.buffer.read(size).decode())

def write_msg(payload):
    data = json.dumps(payload).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
    sys.stdout.buffer.flush()

while True:
    msg = read_msg()
    if msg is None:
        break
    method = msg.get("method")
    if method == "initialize":
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2024-11-05", "capabilities": {}}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        schema = {"type": "object", "properties": {}}
        tool = {"name": "env", "description": "Read env", "inputSchema": schema}
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [tool]}})
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": os.getenv("PLUGIN_AGENT_TEST_ENV", "")}]}
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": result})
''')

    kernel = AgentKernel()
    kernel.load_plugins([
        ToolRuntimePlugin(),
        MCPBridgePlugin({"servers": [{"name": "local", "command": sys.executable, "args": [str(server)], "env": {"PLUGIN_AGENT_TEST_ENV": "configured"}}]}),
    ])
    kernel.start_all()

    result = kernel.invoke("tool.invoke", {"tool_id": "mcp.local.env", "arguments": {}}).payload

    assert result["result"]["content"][0]["text"] == "configured"


def test_mcp_bridge_request_times_out_when_stdio_server_does_not_respond(tmp_path):
    server = tmp_path / "mcp_hanging_server.py"
    server.write_text("import time\ntime.sleep(30)\n")
    previous_handler = signal.getsignal(signal.SIGALRM)

    def fail_if_hung(signum, frame):
        raise AssertionError("MCP request did not use configured timeout")

    signal.signal(signal.SIGALRM, fail_if_hung)
    signal.setitimer(signal.ITIMER_REAL, 2)
    try:
        kernel = AgentKernel()
        kernel.load_plugins([
            ToolRuntimePlugin(),
            MCPBridgePlugin({"servers": [{"name": "local", "command": sys.executable, "args": [str(server)]}], "request_timeout_seconds": 1}),
        ])

        kernel.start_all(raise_on_failed=False)

        assert kernel.runtime_status == "failed"
        assert any(
            diagnostic.code == "plugin_start_failed" and "timed out" in diagnostic.message
            for diagnostic in kernel.diagnostics
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def test_react_loop_marks_tool_call_failed_when_tool_exceeds_timeout():
    kernel = AgentKernel()
    kernel.load_plugins([
        FileMemoryPlugin({"path": None}),
        SlowToolCallingModelPlugin(),
        ToolRuntimePlugin(),
        SlowToolPlugin(),
        ReactAgentLoopPlugin({"limits": {"max_turns": 2, "tool_timeout_ms": 10}}),
    ])
    kernel.start_all()

    result = kernel.invoke("agent.run", {"message": "call slow tool"}).payload

    assert result["tool_audit"][0]["ok"] is False
    assert "timed out" in result["tool_audit"][0]["error"]["message"]


def test_openai_compatible_model_builds_request_and_parses_tool_calls(monkeypatch):
    import json
    import urllib.request

    from plugin_agent.plugins.model_openai_compatible.plugin import OpenAICompatibleModelPlugin

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return json.dumps({
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {"name": "math__add", "arguments": "{\"a\": 3, \"b\": 4}"},
                                }
                            ],
                        }
                    }
                ]
            }).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        captured["auth"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    plugin = OpenAICompatibleModelPlugin({"api_key": "test-key", "model": "test-model", "base_url": "https://example.test/v1", "timeout_seconds": 12})
    result = plugin.invoke("model.chat", {"messages": [{"role": "user", "content": "add"}], "tools": []}, {})

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["body"]["model"] == "test-model"
    assert captured["auth"] == "Bearer test-key"
    assert captured["timeout"] == 12
    assert result["message"]["tool_calls"][0]["tool_id"] == "math__add"
    assert result["message"]["tool_calls"][0]["arguments"] == {"a": 3, "b": 4}


def test_openrouter_and_deepseek_model_plugins_use_provider_defaults(monkeypatch):
    import json
    import urllib.request

    from plugin_agent.plugins.model_deepseek.plugin import DeepSeekModelPlugin
    from plugin_agent.plugins.model_openrouter.plugin import OpenRouterModelPlugin

    captured = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]}).encode()

    def fake_urlopen(request, timeout):
        captured.append({
            "url": request.full_url,
            "body": json.loads(request.data.decode()),
            "auth": request.headers["Authorization"],
            "timeout": timeout,
        })
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    openrouter = OpenRouterModelPlugin({"api_key": "openrouter-key", "timeout_seconds": 9})
    deepseek = DeepSeekModelPlugin({"api_key": "deepseek-key", "timeout_seconds": 10})

    openrouter.invoke("model.chat", {"messages": [{"role": "user", "content": "hi"}], "tools": []}, {})
    deepseek.invoke("model.chat", {"messages": [{"role": "user", "content": "hi"}], "tools": []}, {})

    assert captured[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured[0]["body"]["model"] == "openai/gpt-4o-mini"
    assert captured[0]["auth"] == "Bearer openrouter-key"
    assert captured[0]["timeout"] == 9
    assert captured[1]["url"] == "https://api.deepseek.com/chat/completions"
    assert captured[1]["body"]["model"] == "deepseek-v4-flash"
    assert captured[1]["auth"] == "Bearer deepseek-key"
    assert captured[1]["timeout"] == 10
