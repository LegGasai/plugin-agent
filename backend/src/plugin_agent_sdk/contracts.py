from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class PluginState(StrEnum):
    DISCOVERED = "discovered"
    LOADED = "loaded"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPED = "stopped"
    FAILED = "failed"


class SchemaDefinition(BaseModel):
    schema_ref: str
    json_schema: dict[str, Any]


class CapabilitySpec(BaseModel):
    name: str
    version: str = "1.0.0"
    input_schema_ref: str | None = None
    output_schema_ref: str | None = None
    visibility: str = "agent"


class DependencySpec(BaseModel):
    capability: str
    version: str = ">=0.0.0"
    required: bool = True


class PluginDescriptor(BaseModel):
    id: str
    version: str
    name: str | None = None
    author: str | None = None
    description: str | None = None
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    provides: list[CapabilitySpec] = Field(default_factory=list)
    requires: list[DependencySpec] = Field(default_factory=list)
    config_schema_ref: str | None = None


class CapabilityBinding(BaseModel):
    name: str
    version: str
    provider_instance_id: str
    provider_plugin_id: str
    input_schema_ref: str | None = None
    output_schema_ref: str | None = None
    visibility: str = "agent"


class CapabilityCandidate(BaseModel):
    name: str
    version: str
    provider_instance_id: str
    provider_plugin_id: str


class RuntimeDiagnostic(BaseModel):
    code: str
    severity: str
    message: str
    plugin_instance_id: str | None = None
    plugin_id: str | None = None
    capability: str | None = None
    required: bool = True
    candidates: list[CapabilityCandidate] = Field(default_factory=list)


class RuntimeReport(BaseModel):
    status: str = "ready"
    diagnostics: list[RuntimeDiagnostic] = Field(default_factory=list)
    capability_bindings: dict[str, str] = Field(default_factory=dict)
    startup_order: list[str] = Field(default_factory=list)


class RuntimePythonSpec(BaseModel):
    requires_python: str | None = None
    dependencies: list[str] = Field(default_factory=list)


class RuntimeIsolationSpec(BaseModel):
    process: Literal["package_version", "instance"] = "package_version"
    state: Literal["instance", "shared"] = "instance"


class RuntimeWorkerSpec(BaseModel):
    idle_timeout_seconds: int = 300
    start_timeout_seconds: int = 30
    invoke_timeout_seconds: int = 120


class RuntimeSpec(BaseModel):
    type: Literal["python.in_process", "python.worker"] = "python.in_process"
    entrypoint: str | None = None
    python: RuntimePythonSpec = Field(default_factory=RuntimePythonSpec)
    isolation: RuntimeIsolationSpec = Field(default_factory=RuntimeIsolationSpec)
    worker: RuntimeWorkerSpec = Field(default_factory=RuntimeWorkerSpec)


class PluginRuntimeContext(BaseModel):
    agent_id: str
    instance_id: str
    package_id: str
    package_version: str
    plugin_dir: str
    state_dir: str
    cache_dir: str
    temp_dir: str


class ResourceSpec(BaseModel):
    kind: str
    id: str
    title: str
    description: str = ""
    invoke_capability: str | None = None
    schema_refs: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceBinding(BaseModel):
    resource_id: str
    kind: str
    title: str
    description: str = ""
    provider_instance_id: str
    provider_plugin_id: str
    invoke_capability: str | None = None
    schema_refs: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginPackage(BaseModel):
    package_id: str
    name: str
    version: str
    entrypoint: str | None = None
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    manifest_path: str
    source: str = "builtin"
    market_path: str | None = None
    installed_path: str | None = None
    author: str | None = None
    description: str = ""
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    provides: list[CapabilitySpec] = Field(default_factory=list)
    requires: list[DependencySpec] = Field(default_factory=list)
    resources: list[ResourceSpec] = Field(default_factory=list)
    config_schema_ref: str | None = None
    schemas: list[SchemaDefinition] = Field(default_factory=list)


class InvokeRequest(BaseModel):
    capability: str
    payload: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class InvokeResponse(BaseModel):
    status: str = "ok"
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class StreamEvent(BaseModel):
    type: str
    sequence: int
    run_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolDefinition(BaseModel):
    tool_id: str
    title: str
    description: str
    input_schema_ref: str
    output_schema_ref: str
    invoke_capability: str
