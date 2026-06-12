import pytest
from pydantic import ValidationError

from plugin_agent.kernel import AgentKernel
from plugin_agent_sdk import Plugin, PluginRuntimeContext, PluginState, RuntimeSpec, SchemaDefinition, StreamEvent


class SdkEchoPlugin(Plugin):
    descriptor = {
        "id": "sdk.echo",
        "version": "1.0.0",
        "provides": [
            {
                "name": "sdk.echo",
                "version": "1.0.0",
                "input_schema_ref": "schema://sdk.echo.input.v1",
                "output_schema_ref": "schema://sdk.echo.output.v1",
            }
        ],
    }
    schemas = [
        {
            "schema_ref": "schema://sdk.echo.input.v1",
            "json_schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}, "additionalProperties": False},
        },
        {
            "schema_ref": "schema://sdk.echo.output.v1",
            "json_schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}, "additionalProperties": False},
        },
    ]

    def invoke(self, capability, payload, context):
        return {"text": payload["text"]}


class SdkStreamPlugin(Plugin):
    descriptor = {
        "id": "sdk.stream",
        "version": "1.0.0",
        "provides": [
            {
                "name": "sdk.stream",
                "version": "1.0.0",
                "input_schema_ref": "schema://sdk.stream.input.v1",
                "output_schema_ref": "schema://sdk.stream.event.v1",
            }
        ],
    }
    schemas = [
        {
            "schema_ref": "schema://sdk.stream.input.v1",
            "json_schema": {"type": "object", "additionalProperties": False, "properties": {}},
        },
        {
            "schema_ref": "schema://sdk.stream.event.v1",
            "json_schema": {
                "type": "object",
                "required": ["type", "sequence", "run_id", "payload"],
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string"},
                    "sequence": {"type": "integer"},
                    "run_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
            },
        },
    ]

    def stream(self, capability, payload, context):
        yield StreamEvent(type="stream_started", sequence=0, run_id=context["run_id"], payload={"ok": True}).model_dump()


def test_public_sdk_plugin_can_be_loaded_by_private_kernel():
    kernel = AgentKernel()
    plugin = SdkEchoPlugin(instance_id="sdk-echo-1")

    kernel.load_plugin(plugin)
    kernel.start_all()

    assert plugin.state == PluginState.ACTIVE
    assert kernel.invoke("sdk.echo", {"text": "hello"}).payload == {"text": "hello"}


def test_public_sdk_exports_contract_models():
    schema = SchemaDefinition(schema_ref="schema://sdk.contract.v1", json_schema={"type": "object"})

    assert schema.schema_ref == "schema://sdk.contract.v1"


def test_runtime_spec_parses_worker_runtime_options():
    runtime = RuntimeSpec.model_validate(
        {
            "type": "python.worker",
            "entrypoint": "plugin.py:WorkerPlugin",
            "python": {"requires_python": ">=3.11", "dependencies": ["httpx>=0.27"]},
            "isolation": {"process": "instance", "state": "shared"},
            "worker": {"idle_timeout_seconds": 10, "start_timeout_seconds": 3, "invoke_timeout_seconds": 7},
        }
    )

    assert runtime.type == "python.worker"
    assert runtime.python.dependencies == ["httpx>=0.27"]
    assert runtime.isolation.process == "instance"
    assert runtime.isolation.state == "shared"
    assert runtime.worker.invoke_timeout_seconds == 7


def test_runtime_spec_rejects_invalid_isolation_options():
    with pytest.raises(ValidationError):
        RuntimeSpec.model_validate({"type": "python.worker", "isolation": {"process": "agent"}})


def test_plugin_runtime_context_is_exposed_on_sdk_plugin():
    plugin = SdkEchoPlugin(instance_id="sdk-echo-ctx")
    plugin.runtime_context = PluginRuntimeContext(
        agent_id="agent-1",
        instance_id="sdk-echo-ctx",
        package_id="sdk.echo",
        package_version="1.0.0",
        plugin_dir="/tmp/plugin",
        state_dir="/tmp/state",
        cache_dir="/tmp/cache",
        temp_dir="/tmp/tmp",
    )

    assert plugin.runtime_context.state_dir == "/tmp/state"


def test_public_sdk_plugin_stream_defaults_to_not_supported():
    plugin = SdkEchoPlugin()

    with pytest.raises(NotImplementedError):
        list(plugin.stream("sdk.echo", {"text": "hello"}, {"run_id": "run-test"}))


def test_kernel_routes_streaming_capabilities_and_validates_events():
    kernel = AgentKernel()
    kernel.load_plugin(SdkStreamPlugin(instance_id="sdk-stream-1"))
    kernel.start_all()

    events = list(kernel.stream("sdk.stream", {}, {"run_id": "run-test"}))

    assert events == [{"type": "stream_started", "sequence": 0, "run_id": "run-test", "payload": {"ok": True}}]
