
import pytest

from plugin_agent.contracts import SchemaDefinition
from plugin_agent.kernel import AgentKernel, KernelInvokeError, PluginBase, PluginState


class EchoPlugin(PluginBase):
    descriptor = {
        "id": "test.echo",
        "version": "1.0.0",
        "provides": [
            {
                "name": "test.echo",
                "version": "1.0.0",
                "input_schema_ref": "schema://test.echo.input.v1",
                "output_schema_ref": "schema://test.echo.output.v1",
            }
        ],
    }
    schemas = [
        {
            "schema_ref": "schema://test.echo.input.v1",
            "json_schema": {
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        {
            "schema_ref": "schema://test.echo.output.v1",
            "json_schema": {
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    ]

    def invoke(self, capability, payload, context):
        return {"text": payload["text"]}


class NeedsMissingPlugin(PluginBase):
    descriptor = {
        "id": "test.needs_missing",
        "version": "1.0.0",
        "requires": [{"capability": "missing.capability", "version": ">=1.0 <2.0", "required": True}],
    }


class SharedProviderPlugin(PluginBase):
    descriptor = {
        "id": "test.shared_provider",
        "version": "1.0.0",
        "provides": [{"name": "test.shared", "version": "1.5.0"}],
    }

    def invoke(self, capability, payload, context):
        return {"provider": self.instance_id}


class OtherSharedProviderPlugin(PluginBase):
    descriptor = {
        "id": "test.other_shared_provider",
        "version": "1.0.0",
        "provides": [{"name": "test.shared", "version": "1.5.0"}],
    }

    def invoke(self, capability, payload, context):
        return {"provider": self.instance_id}


class NeedsSharedPlugin(PluginBase):
    descriptor = {
        "id": "test.needs_shared",
        "version": "1.0.0",
        "requires": [{"capability": "test.shared", "version": ">=1.0 <2.0", "required": True}],
        "provides": [{"name": "test.consumer", "version": "1.0.0"}],
    }

    def invoke(self, capability, payload, context):
        return self.kernel.invoke("test.shared", {}, context).payload


class NeedsSharedV2Plugin(PluginBase):
    descriptor = {
        "id": "test.needs_shared_v2",
        "version": "1.0.0",
        "requires": [{"capability": "test.shared", "version": ">=2.0 <3.0", "required": True}],
    }


class OptionalSharedPlugin(PluginBase):
    descriptor = {
        "id": "test.optional_shared",
        "version": "1.0.0",
        "requires": [{"capability": "test.shared", "version": ">=1.0 <2.0", "required": False}],
        "provides": [{"name": "test.optional", "version": "1.0.0"}],
    }

    def invoke(self, capability, payload, context):
        return {"ok": True}


def test_schema_registry_rejects_overwrite():
    kernel = AgentKernel()
    schema = SchemaDefinition(schema_ref="schema://x.input.v1", json_schema={"type": "object"})

    kernel.schema_registry.register(schema)

    with pytest.raises(ValueError, match="already registered"):
        kernel.schema_registry.register(schema)


def test_plugin_registers_capability_and_invoke_validates_payloads():
    kernel = AgentKernel()
    plugin = EchoPlugin()

    kernel.load_plugin(plugin)
    kernel.start_all()

    assert plugin.state == PluginState.ACTIVE
    assert kernel.capability_registry.get("test.echo").provider_plugin_id == "test.echo"
    assert kernel.invoke("test.echo", {"text": "hello"}).payload == {"text": "hello"}

    with pytest.raises(ValueError, match="input schema"):
        kernel.invoke("test.echo", {"text": 123})


def test_required_dependency_blocks_plugin_start():
    kernel = AgentKernel()
    plugin = NeedsMissingPlugin()

    kernel.load_plugin(plugin)

    with pytest.raises(ValueError, match="missing required capability"):
        kernel.start_all()

    assert plugin.state == PluginState.FAILED


def test_dependency_version_mismatch_is_reported():
    kernel = AgentKernel()
    kernel.load_plugins([SharedProviderPlugin(instance_id="provider-1"), NeedsSharedV2Plugin(instance_id="consumer-1")])

    with pytest.raises(ValueError, match="version_mismatch"):
        kernel.start_all()

    assert any(diagnostic.code == "version_mismatch" for diagnostic in kernel.diagnostics)
    assert kernel.plugins["consumer-1"].state == PluginState.FAILED


def test_optional_dependency_degrades_runtime_without_blocking_startup():
    kernel = AgentKernel()
    plugin = OptionalSharedPlugin(instance_id="optional-1")

    kernel.load_plugin(plugin)
    kernel.start_all()

    assert plugin.state == PluginState.ACTIVE
    assert kernel.runtime_status == "degraded"
    assert any(diagnostic.code == "missing_dependency" and diagnostic.severity == "warning" for diagnostic in kernel.diagnostics)


def test_duplicate_provider_requires_explicit_binding():
    kernel = AgentKernel()
    kernel.load_plugins(
        [
            SharedProviderPlugin(instance_id="provider-1"),
            OtherSharedProviderPlugin(instance_id="provider-2"),
            NeedsSharedPlugin(instance_id="consumer-1"),
        ]
    )

    with pytest.raises(ValueError, match="provider_conflict"):
        kernel.start_all()

    assert any(diagnostic.code == "provider_conflict" for diagnostic in kernel.diagnostics)
    assert kernel.plugins["consumer-1"].state == PluginState.FAILED


def test_explicit_binding_selects_provider_for_duplicate_capability():
    kernel = AgentKernel(capability_bindings={"test.shared": "provider-2"})
    kernel.load_plugins(
        [
            SharedProviderPlugin(instance_id="provider-1"),
            OtherSharedProviderPlugin(instance_id="provider-2"),
            NeedsSharedPlugin(instance_id="consumer-1"),
        ]
    )

    kernel.start_all()

    assert kernel.runtime_status == "ready"
    assert kernel.capability_registry.get("test.shared").provider_instance_id == "provider-2"
    assert kernel.invoke("test.consumer", {}).payload == {"provider": "provider-2"}
    assert kernel.startup_order == ["provider-1", "provider-2", "consumer-1"]


def test_discovery_reports_candidates_selected_provider_and_schema_refs():
    kernel = AgentKernel(capability_bindings={"test.shared": "provider-2"})
    kernel.load_plugins(
        [
            SharedProviderPlugin(instance_id="provider-1"),
            OtherSharedProviderPlugin(instance_id="provider-2"),
        ]
    )

    kernel.start_all()

    discovered = kernel.discover_capability("test.shared")

    assert discovered["capability"] == "test.shared"
    assert discovered["status"] == "ready"
    assert discovered["selected_provider_instance_id"] == "provider-2"
    assert [candidate["provider_instance_id"] for candidate in discovered["candidates"]] == ["provider-1", "provider-2"]
    assert discovered["binding"] == kernel.capability_registry.get("test.shared").model_dump()


def test_invoke_missing_capability_raises_structured_error():
    kernel = AgentKernel()

    with pytest.raises(KernelInvokeError) as exc_info:
        kernel.invoke("missing.capability", {})

    error = exc_info.value.error
    assert error["code"] == "capability_not_found"
    assert error["capability"] == "missing.capability"
    assert error["retryable"] is False


def test_invoke_schema_failure_raises_structured_error_without_losing_value_error_compatibility():
    kernel = AgentKernel()
    kernel.load_plugin(EchoPlugin())
    kernel.start_all()

    with pytest.raises(ValueError, match="input schema") as exc_info:
        kernel.invoke("test.echo", {"text": 123})

    assert isinstance(exc_info.value, KernelInvokeError)
    assert exc_info.value.error["code"] == "input_schema_invalid"
    assert exc_info.value.error["capability"] == "test.echo"
