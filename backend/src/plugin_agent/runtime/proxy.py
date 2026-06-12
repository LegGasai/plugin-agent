from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from plugin_agent.runtime.manager import PluginRuntimeManager, WorkerRuntimeError
from plugin_agent_sdk import Plugin as PluginBase
from plugin_agent_sdk import (
    PluginDescriptor,
    PluginPackage,
    PluginRuntimeContext,
    PluginState,
    ResourceSpec,
)


class RemotePluginProxy(PluginBase):
    def __init__(
        self,
        package: PluginPackage,
        manager: PluginRuntimeManager,
        installed_path: str,
        config: dict[str, Any] | None = None,
        instance_id: str | None = None,
        agent_id: str = "adhoc-agent",
    ) -> None:
        self.package = package
        self.manager = manager
        self.installed_path = installed_path
        self.config = config or {}
        self.plugin_dir = Path(installed_path)
        self.manifest_path = self.plugin_dir / "plugin.yaml"
        self.config_path = self.plugin_dir / "config.yaml"
        self.descriptor_model = PluginDescriptor(
            id=package.package_id,
            version=package.version,
            name=package.name,
            author=package.author,
            description=package.description,
            categories=package.categories,
            tags=package.tags,
            provides=package.provides,
            requires=package.requires,
            config_schema_ref=package.config_schema_ref,
        )
        self.schemas = [schema.model_dump() for schema in package.schemas]
        self.tool_definitions = []
        self.resource_specs = [ResourceSpec.model_validate(resource) for resource in package.resources]
        self.id = package.package_id
        self.package_id = package.package_id
        self.instance_id = instance_id or package.package_id
        self.agent_id = agent_id
        self.state = PluginState.DISCOVERED
        self.generation = 1
        self.kernel: Any | None = None
        self.runtime_context: PluginRuntimeContext | None = None
        self.worker_status = "stopped"
        self.env_status = "unknown"

    def package_model(self) -> PluginPackage:
        return self.package

    def start(self, kernel: Any) -> None:
        self.kernel = kernel
        if not self.package.entrypoint:
            raise ValueError(f"plugin package {self.package.package_id} has no runtime entrypoint")
        context = self.manager.start_instance(
            self.package,
            self.installed_path,
            self.package.entrypoint,
            self.config,
            self.instance_id,
            self.agent_id,
            kernel,
        )
        self.runtime_context = PluginRuntimeContext.model_validate(context)
        self.worker_status = self.manager.worker_status(self.package, self.instance_id)
        self.env_status = self.manager.env_status.get(f"{self.package.package_id}@{self.package.version}", "unknown")
        self.tool_definitions = context.get("tool_definitions", [])
        self.resource_specs = [ResourceSpec.model_validate(resource) for resource in context.get("resources", [])]

    def after_start_all(self, kernel: Any) -> None:
        description = self.manager.after_start_all(self.package, self.instance_id, kernel)
        self.tool_definitions = description.get("tool_definitions", self.tool_definitions)
        if "resources" in description:
            self.resource_specs = [ResourceSpec.model_validate(resource) for resource in description["resources"]]

    def stop(self) -> None:
        try:
            self.manager.stop_instance(self.package, self.instance_id)
        finally:
            self.kernel = None
            self.worker_status = self.manager.worker_status(self.package, self.instance_id)

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.manager.invoke(self.package, self.instance_id, capability, payload, context)
        except WorkerRuntimeError as exc:
            raise RuntimeError(f"{exc.code}: {exc}") from exc

    def stream(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> Iterator[dict[str, Any]]:
        try:
            yield from self.manager.stream(self.package, self.instance_id, capability, payload, context)
        except WorkerRuntimeError as exc:
            raise RuntimeError(f"{exc.code}: {exc}") from exc
