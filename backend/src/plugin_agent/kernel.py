from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Iterable

from jsonschema import ValidationError, validate
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from plugin_agent_sdk import (
    CapabilityBinding,
    CapabilityCandidate,
    CapabilitySpec,
    InvokeResponse,
    PluginState,
    ResourceBinding,
    ResourceSpec,
    RuntimeDiagnostic,
    SchemaDefinition,
    ToolDefinition,
)
from plugin_agent_sdk import Plugin as PluginBase


class KernelInvokeError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        capability: str | None = None,
        provider_instance_id: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error = {
            "code": code,
            "message": message,
            "capability": capability,
            "provider_instance_id": provider_instance_id,
            "retryable": retryable,
            "details": details or {},
        }


class SchemaRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, SchemaDefinition] = {}

    def register(self, schema: SchemaDefinition) -> None:
        if schema.schema_ref in self._schemas:
            raise ValueError(f"schema {schema.schema_ref} is already registered")
        self._schemas[schema.schema_ref] = schema

    def get(self, schema_ref: str) -> SchemaDefinition:
        try:
            return self._schemas[schema_ref]
        except KeyError as exc:
            raise KeyError(f"schema {schema_ref} is not registered") from exc

    def validate_payload(self, schema_ref: str | None, payload: dict[str, Any], phase: str) -> None:
        if not schema_ref:
            return
        schema = self.get(schema_ref).json_schema
        try:
            validate(instance=payload, schema=schema)
        except ValidationError as exc:
            path = ".".join(str(part) for part in exc.path) or "payload"
            raise ValueError(f"{phase} schema validation failed at {path}: {exc.message}") from exc

    def list(self) -> list[SchemaDefinition]:
        return list(self._schemas.values())


class CapabilityRegistry:
    def __init__(self) -> None:
        self._bindings: dict[str, CapabilityBinding] = {}

    def register(self, spec: CapabilitySpec, provider_plugin_id: str, provider_instance_id: str | None = None) -> None:
        if spec.name in self._bindings:
            raise ValueError(f"capability {spec.name} is already registered")
        self._bindings[spec.name] = CapabilityBinding(
            name=spec.name,
            version=spec.version,
            provider_instance_id=provider_instance_id or provider_plugin_id,
            provider_plugin_id=provider_plugin_id,
            input_schema_ref=spec.input_schema_ref,
            output_schema_ref=spec.output_schema_ref,
            visibility=spec.visibility,
        )

    def get(self, name: str) -> CapabilityBinding:
        try:
            return self._bindings[name]
        except KeyError as exc:
            raise KeyError(f"capability {name} is not registered") from exc

    def has(self, name: str) -> bool:
        return name in self._bindings

    def list(self) -> list[CapabilityBinding]:
        return sorted(self._bindings.values(), key=lambda binding: binding.name)


class ResourceRegistry:
    def __init__(self) -> None:
        self._resources: dict[str, ResourceBinding] = {}

    def register(self, spec: ResourceSpec, provider_plugin_id: str, provider_instance_id: str) -> None:
        key = f"{provider_instance_id}:{spec.kind}:{spec.id}"
        if key in self._resources:
            raise ValueError(f"resource {spec.kind}:{spec.id} is already registered by {provider_instance_id}")
        self._resources[key] = ResourceBinding(
            resource_id=spec.id,
            kind=spec.kind,
            title=spec.title,
            description=spec.description,
            provider_instance_id=provider_instance_id,
            provider_plugin_id=provider_plugin_id,
            invoke_capability=spec.invoke_capability,
            schema_refs=spec.schema_refs,
            metadata=spec.metadata,
        )

    def list(self, kind: str | None = None) -> list[ResourceBinding]:
        resources = list(self._resources.values())
        if kind is not None:
            resources = [resource for resource in resources if resource.kind == kind]
        return sorted(resources, key=lambda resource: (resource.kind, resource.resource_id, resource.provider_instance_id))


class AgentKernel:
    def __init__(self, capability_bindings: dict[str, str] | None = None) -> None:
        self.schema_registry = SchemaRegistry()
        self.capability_registry = CapabilityRegistry()
        self.resource_registry = ResourceRegistry()
        self.plugins: dict[str, PluginBase] = {}
        self.capability_bindings = capability_bindings or {}
        self.diagnostics: list[RuntimeDiagnostic] = []
        self.runtime_status = "ready"
        self.startup_order: list[str] = []
        self._capability_candidates: dict[str, list[CapabilityCandidate]] = {}
        self._selected_capability_providers: dict[str, CapabilityCandidate] = {}

    def load_plugin(self, plugin: PluginBase) -> None:
        if plugin.instance_id in self.plugins:
            raise ValueError(f"plugin instance {plugin.instance_id} is already loaded")
        for schema_data in plugin.schemas:
            schema = SchemaDefinition.model_validate(schema_data)
            if schema.schema_ref in self.schema_registry._schemas:
                existing = self.schema_registry.get(schema.schema_ref)
                if existing.json_schema != schema.json_schema:
                    raise ValueError(f"schema {schema.schema_ref} is already registered with different content")
                continue
            self.schema_registry.register(schema)
        self.plugins[plugin.instance_id] = plugin
        plugin.state = PluginState.LOADED

    def load_plugins(self, plugins: Iterable[PluginBase]) -> None:
        for plugin in plugins:
            self.load_plugin(plugin)

    def start_all(self, raise_on_failed: bool = True) -> None:
        self.capability_registry = CapabilityRegistry()
        self.resource_registry = ResourceRegistry()
        self.diagnostics = []
        self.runtime_status = "ready"
        self.startup_order = []
        candidates = self._collect_capability_candidates()
        self._capability_candidates = candidates
        self._selected_capability_providers = self._select_capability_providers(candidates)
        pending = [plugin for plugin in self.plugins.values() if plugin.state == PluginState.LOADED]
        progressed = True
        while pending and progressed:
            progressed = False
            remaining: list[PluginBase] = []
            for plugin in pending:
                dependency_state = [
                    self._check_dependency(plugin, dep, candidates)
                    for dep in plugin.descriptor_model.requires
                ]
                if any(state == "blocked" for state in dependency_state):
                    plugin.state = PluginState.FAILED
                    continue
                if any(state == "waiting" for state in dependency_state):
                    remaining.append(plugin)
                    continue
                self._start_plugin(plugin)
                progressed = True
            pending = remaining

        if pending:
            for plugin in pending:
                plugin.state = PluginState.FAILED
                for dep in plugin.descriptor_model.requires:
                    if dep.required:
                        self._add_diagnostic(
                            "provider_not_active",
                            "error",
                            f"{plugin.id} requires {dep.capability}, but the selected provider did not become active",
                            plugin,
                            dep.capability,
                            dep.required,
                            candidates.get(dep.capability, []),
                        )

        for plugin in self.plugins.values():
            if plugin.state == PluginState.ACTIVE:
                plugin.after_start_all(self)
        self._refresh_runtime_status()
        if raise_on_failed and self.runtime_status == "failed":
            raise ValueError(self._diagnostic_summary())

    def _start_plugin(self, plugin: PluginBase) -> None:
        plugin.state = PluginState.STARTING
        try:
            plugin.start(self)
            for capability in plugin.descriptor_model.provides:
                selected = self._selected_capability_providers.get(capability.name)
                if selected and selected.provider_instance_id == plugin.instance_id:
                    self.capability_registry.register(capability, plugin.package_id, plugin.instance_id)
            for resource in plugin.resource_specs:
                self.resource_registry.register(resource, plugin.package_id, plugin.instance_id)
            plugin.state = PluginState.ACTIVE
            self.startup_order.append(plugin.instance_id)
        except Exception as exc:
            plugin.state = PluginState.FAILED
            code = str(getattr(exc, "code", "plugin_start_failed"))
            self._add_diagnostic(
                code,
                "error",
                f"{plugin.id} failed to start: {exc}",
                plugin,
            )

    def _collect_capability_candidates(self) -> dict[str, list[CapabilityCandidate]]:
        candidates: dict[str, list[CapabilityCandidate]] = {}
        for plugin in self.plugins.values():
            for capability in plugin.descriptor_model.provides:
                candidates.setdefault(capability.name, []).append(
                    CapabilityCandidate(
                        name=capability.name,
                        version=capability.version,
                        provider_instance_id=plugin.instance_id,
                        provider_plugin_id=plugin.package_id,
                    )
                )
        return candidates

    def _select_capability_providers(
        self, candidates: dict[str, list[CapabilityCandidate]]
    ) -> dict[str, CapabilityCandidate]:
        selected: dict[str, CapabilityCandidate] = {}
        for capability, capability_candidates in candidates.items():
            bound_instance_id = self.capability_bindings.get(capability)
            if bound_instance_id is None and capability.endswith(".stream"):
                bound_instance_id = self.capability_bindings.get(capability.removesuffix(".stream"))
            if bound_instance_id:
                bound = next(
                    (candidate for candidate in capability_candidates if candidate.provider_instance_id == bound_instance_id),
                    None,
                )
                if bound is None:
                    self._add_diagnostic(
                        "binding_missing_provider",
                        "error",
                        f"{capability} is bound to {bound_instance_id}, but that provider is not installed in this Agent",
                        capability=capability,
                        candidates=capability_candidates,
                    )
                    continue
                selected[capability] = bound
                continue
            if capability.endswith(".stream"):
                base = selected.get(capability.removesuffix(".stream"))
                if base is not None:
                    paired = next(
                        (
                            candidate
                            for candidate in capability_candidates
                            if candidate.provider_instance_id == base.provider_instance_id
                        ),
                        None,
                    )
                    if paired is not None:
                        selected[capability] = paired
                        continue
            if len(capability_candidates) == 1:
                selected[capability] = capability_candidates[0]
            else:
                self._add_diagnostic(
                    "provider_conflict",
                    "error",
                    f"{capability} has multiple providers and requires an explicit Agent capability binding",
                    capability=capability,
                    candidates=capability_candidates,
                )
        return selected

    def _check_dependency(
        self,
        plugin: PluginBase,
        dep: Any,
        candidates: dict[str, list[CapabilityCandidate]],
    ) -> str:
        capability_candidates = candidates.get(dep.capability, [])
        matching = [candidate for candidate in capability_candidates if self._version_matches(candidate.version, dep.version)]
        severity = "error" if dep.required else "warning"
        if not capability_candidates:
            self._add_diagnostic(
                "missing_dependency",
                severity,
                f"{plugin.id} requires {dep.capability}, but no provider is installed in this Agent",
                plugin,
                dep.capability,
                dep.required,
                capability_candidates,
            )
            return "blocked" if dep.required else "ready"
        if not matching:
            self._add_diagnostic(
                "version_mismatch",
                severity,
                f"{plugin.id} requires {dep.capability} {dep.version}, but installed providers do not satisfy it",
                plugin,
                dep.capability,
                dep.required,
                capability_candidates,
            )
            return "blocked" if dep.required else "ready"
        selected = self._selected_capability_providers.get(dep.capability)
        if selected is None:
            self._add_diagnostic(
                "provider_conflict",
                severity,
                f"{plugin.id} requires {dep.capability}, but multiple providers are available and none is bound",
                plugin,
                dep.capability,
                dep.required,
                matching,
            )
            return "blocked" if dep.required else "ready"
        if selected not in matching:
            self._add_diagnostic(
                "version_mismatch",
                severity,
                f"{plugin.id} is bound to {selected.provider_instance_id} for {dep.capability}, but that provider does not satisfy {dep.version}",
                plugin,
                dep.capability,
                dep.required,
                capability_candidates,
            )
            return "blocked" if dep.required else "ready"
        if not self.capability_registry.has(dep.capability):
            return "waiting"
        return "ready"

    def _version_matches(self, version: str, requirement: str) -> bool:
        try:
            normalized_requirement = ",".join(requirement.split())
            return Version(version) in SpecifierSet(normalized_requirement)
        except (InvalidSpecifier, InvalidVersion):
            return version == requirement

    def _add_diagnostic(
        self,
        code: str,
        severity: str,
        message: str,
        plugin: PluginBase | None = None,
        capability: str | None = None,
        required: bool = True,
        candidates: list[CapabilityCandidate] | None = None,
    ) -> None:
        diagnostic = RuntimeDiagnostic(
            code=code,
            severity=severity,
            message=message,
            plugin_instance_id=plugin.instance_id if plugin else None,
            plugin_id=plugin.package_id if plugin else None,
            capability=capability,
            required=required,
            candidates=candidates or [],
        )
        key = diagnostic.model_dump_json()
        if not any(existing.model_dump_json() == key for existing in self.diagnostics):
            self.diagnostics.append(diagnostic)

    def _refresh_runtime_status(self) -> None:
        if any(diagnostic.severity == "error" for diagnostic in self.diagnostics):
            self.runtime_status = "failed"
        elif any(diagnostic.severity == "warning" for diagnostic in self.diagnostics):
            self.runtime_status = "degraded"
        else:
            self.runtime_status = "ready"

    def _diagnostic_summary(self) -> str:
        if not self.diagnostics:
            return "missing required capability for plugin startup"
        messages = "; ".join(f"{diagnostic.code}: {diagnostic.message}" for diagnostic in self.diagnostics)
        return f"missing required capability for plugin startup: {messages}"

    def stop_all(self) -> None:
        for plugin in reversed(list(self.plugins.values())):
            if plugin.state == PluginState.ACTIVE:
                plugin.stop()
                plugin.state = PluginState.STOPPED

    def invoke(
        self, capability: str, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None
    ) -> InvokeResponse:
        if not self.capability_registry.has(capability):
            candidates = self._capability_candidates.get(capability, [])
            code = "provider_conflict" if candidates else "capability_not_found"
            message = (
                f"{capability} has providers but no selected active binding"
                if candidates
                else f"capability {capability} is not registered"
            )
            raise KernelInvokeError(
                code,
                message,
                capability=capability,
                details={"candidates": [candidate.model_dump() for candidate in candidates]},
            )
        binding = self.capability_registry.get(capability)
        payload = payload or {}
        context = context or {}
        try:
            self.schema_registry.validate_payload(binding.input_schema_ref, payload, "input")
        except ValueError as exc:
            raise KernelInvokeError("input_schema_invalid", str(exc), capability=capability, provider_instance_id=binding.provider_instance_id) from exc
        provider = self.plugins.get(binding.provider_instance_id) or self.plugins.get(binding.provider_plugin_id)
        if provider is None:
            raise KernelInvokeError(
                "provider_unavailable",
                f"provider instance {binding.provider_instance_id} is not loaded",
                capability=capability,
                provider_instance_id=binding.provider_instance_id,
                retryable=True,
            )
        if provider.state != PluginState.ACTIVE:
            raise KernelInvokeError(
                "provider_unavailable",
                f"provider {provider.id} is not active",
                capability=capability,
                provider_instance_id=binding.provider_instance_id,
                retryable=True,
            )
        try:
            result = provider.invoke(capability, payload, context)
        except KernelInvokeError:
            raise
        except Exception as exc:
            raise KernelInvokeError(
                "provider_error",
                str(exc),
                capability=capability,
                provider_instance_id=binding.provider_instance_id,
            ) from exc
        try:
            self.schema_registry.validate_payload(binding.output_schema_ref, result, "output")
        except ValueError as exc:
            raise KernelInvokeError("output_schema_invalid", str(exc), capability=capability, provider_instance_id=binding.provider_instance_id) from exc
        return InvokeResponse(payload=result)

    def stream(
        self, capability: str, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        if not self.capability_registry.has(capability):
            candidates = self._capability_candidates.get(capability, [])
            code = "provider_conflict" if candidates else "capability_not_found"
            raise KernelInvokeError(
                code,
                f"capability {capability} is not registered",
                capability=capability,
                details={"candidates": [candidate.model_dump() for candidate in candidates]},
            )
        binding = self.capability_registry.get(capability)
        payload = payload or {}
        context = context or {}
        try:
            self.schema_registry.validate_payload(binding.input_schema_ref, payload, "input")
        except ValueError as exc:
            raise KernelInvokeError("input_schema_invalid", str(exc), capability=capability, provider_instance_id=binding.provider_instance_id) from exc
        provider = self.plugins.get(binding.provider_instance_id) or self.plugins.get(binding.provider_plugin_id)
        if provider is None:
            raise KernelInvokeError(
                "provider_unavailable",
                f"provider instance {binding.provider_instance_id} is not loaded",
                capability=capability,
                provider_instance_id=binding.provider_instance_id,
                retryable=True,
            )
        if provider.state != PluginState.ACTIVE:
            raise KernelInvokeError(
                "provider_unavailable",
                f"provider {provider.id} is not active",
                capability=capability,
                provider_instance_id=binding.provider_instance_id,
                retryable=True,
            )
        try:
            for event in provider.stream(capability, payload, context):
                try:
                    self.schema_registry.validate_payload(binding.output_schema_ref, event, "output")
                except ValueError as exc:
                    raise KernelInvokeError("output_schema_invalid", str(exc), capability=capability, provider_instance_id=binding.provider_instance_id) from exc
                yield event
        except KernelInvokeError:
            raise
        except Exception as exc:
            raise KernelInvokeError(
                "provider_error",
                str(exc),
                capability=capability,
                provider_instance_id=binding.provider_instance_id,
            ) from exc

    def discover_capability(self, capability: str) -> dict[str, Any]:
        candidates = self._capability_candidates.get(capability, [])
        selected = self._selected_capability_providers.get(capability)
        binding = self.capability_registry.get(capability).model_dump() if self.capability_registry.has(capability) else None
        if not candidates:
            status = "not_found"
        elif binding:
            status = "ready"
        elif self.capability_bindings.get(capability):
            status = "binding_missing"
        elif len(candidates) > 1:
            status = "conflict"
        else:
            status = "unavailable"
        return {
            "capability": capability,
            "status": status,
            "selected_provider_instance_id": selected.provider_instance_id if selected else None,
            "binding": binding,
            "candidates": self._capability_candidate_details(capability),
        }

    def discover_capabilities(self) -> list[dict[str, Any]]:
        names = sorted(set(self._capability_candidates) | {binding.name for binding in self.capability_registry.list()})
        return [self.discover_capability(name) for name in names]

    def get_schema(self, schema_ref: str) -> dict[str, Any]:
        return self.schema_registry.get(schema_ref).json_schema

    def _capability_candidate_details(self, capability: str) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for plugin in self.plugins.values():
            for spec in plugin.descriptor_model.provides:
                if spec.name != capability:
                    continue
                details.append(
                    {
                        "capability": spec.name,
                        "version": spec.version,
                        "provider_instance_id": plugin.instance_id,
                        "provider_plugin_id": plugin.package_id,
                        "input_schema_ref": spec.input_schema_ref,
                        "output_schema_ref": spec.output_schema_ref,
                        "visibility": spec.visibility,
                        "state": plugin.state.value,
                    }
                )
        return sorted(details, key=lambda item: item["provider_instance_id"])

    def collect_tool_definitions(self) -> list[ToolDefinition]:
        tools: list[ToolDefinition] = []
        for resource in self.resource_registry.list("tool"):
            if resource.invoke_capability:
                tools.append(
                    ToolDefinition(
                        tool_id=resource.resource_id,
                        title=resource.title,
                        description=resource.description,
                        input_schema_ref=resource.schema_refs.get("input", ""),
                        output_schema_ref=resource.schema_refs.get("output", ""),
                        invoke_capability=resource.invoke_capability,
                    )
                )
        for plugin in self.plugins.values():
            for tool_data in getattr(plugin, "tool_definitions", []):
                tool = ToolDefinition.model_validate(tool_data)
                if not any(existing.tool_id == tool.tool_id for existing in tools):
                    tools.append(tool)
        return tools


def build_default_kernel() -> AgentKernel:
    from plugin_agent.services.assembly_service import DEFAULT_AGENT_PLUGIN_IDS, AgentAssemblyService

    return AgentAssemblyService().build_kernel(DEFAULT_AGENT_PLUGIN_IDS, raise_on_failed=False)
