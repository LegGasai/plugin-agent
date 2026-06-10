from __future__ import annotations

import inspect
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from plugin_agent_sdk.contracts import (
    PluginDescriptor,
    PluginPackage,
    PluginState,
    ResourceSpec,
    RuntimeSpec,
    SchemaDefinition,
)


class Plugin:
    descriptor: dict[str, Any] = {}
    schemas: list[dict[str, Any]] = []
    tool_definitions: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []

    def __init__(self, config: dict[str, Any] | None = None, instance_id: str | None = None) -> None:
        self.plugin_dir = Path(inspect.getfile(self.__class__)).parent
        self.manifest_path = self.plugin_dir / "plugin.yaml"
        if not self.manifest_path.exists():
            self.manifest_path = self.plugin_dir / "manifest.yaml"
        self.config_path = self.plugin_dir / "config.yaml"
        manifest = self._read_yaml(self.manifest_path) if self.manifest_path.exists() else {}
        file_config = self._read_yaml(self.config_path) if self.config_path.exists() else {}
        descriptor = self._descriptor_from_manifest(manifest)
        schemas = manifest.get("schemas", self.schemas)
        tool_definitions = manifest.get("tool_definitions", self.tool_definitions)
        resources = manifest.get("resources", self.resources)

        self.config = {**file_config, **(config or {})}
        self.descriptor_model = PluginDescriptor.model_validate(descriptor)
        self.schemas = schemas
        self.tool_definitions = tool_definitions
        self.resource_specs = [ResourceSpec.model_validate(resource) for resource in resources]
        self.id = self.descriptor_model.id
        self.package_id = self.descriptor_model.id
        self.instance_id = instance_id or self.package_id
        self.state = PluginState.DISCOVERED
        self.generation = 1
        self.kernel: Any | None = None

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML object")
        return data

    def _descriptor_from_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        if "descriptor" in manifest:
            return manifest.get("descriptor") or self.descriptor
        if "id" in manifest:
            return {
                "id": manifest["id"],
                "version": manifest.get("version", "1.0.0"),
                "name": manifest.get("name"),
                "author": manifest.get("author"),
                "description": manifest.get("description"),
                "categories": manifest.get("categories", []),
                "tags": manifest.get("tags", []),
                "provides": manifest.get("provides", []),
                "requires": manifest.get("requires", []),
                "config_schema_ref": manifest.get("config_schema_ref"),
            }
        return self.descriptor

    def package_model(self) -> PluginPackage:
        runtime_data = self._read_yaml(self.manifest_path).get("runtime", {}) if self.manifest_path.exists() else {}
        runtime = RuntimeSpec.model_validate(runtime_data or {})
        return PluginPackage(
            package_id=self.package_id,
            name=self.descriptor_model.name or self.package_id,
            version=self.descriptor_model.version,
            entrypoint=runtime.entrypoint,
            runtime=runtime,
            manifest_path=str(self.manifest_path),
            author=self.descriptor_model.author,
            description=self.descriptor_model.description or "",
            categories=self.descriptor_model.categories,
            tags=self.descriptor_model.tags,
            provides=self.descriptor_model.provides,
            requires=self.descriptor_model.requires,
            resources=self.resource_specs,
            config_schema_ref=self.descriptor_model.config_schema_ref,
            schemas=[SchemaDefinition.model_validate(schema) for schema in self.schemas],
        )

    def start(self, kernel: Any) -> None:
        self.kernel = kernel

    def stop(self) -> None:
        self.kernel = None

    def after_start_all(self, kernel: Any) -> None:
        pass

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.id} does not handle {capability}")

    def stream(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> Iterator[dict[str, Any]]:
        raise NotImplementedError(f"{self.id} does not stream {capability}")
