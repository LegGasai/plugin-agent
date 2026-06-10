from __future__ import annotations

from typing import Any, TypedDict


class AgentRecord(TypedDict, total=False):
    agent_id: str
    name: str
    description: str
    entry_loop_instance_id: str | None
    capability_bindings: dict[str, str]
    status: str
    created_at: str
    updated_at: str


class PluginInstanceRecord(TypedDict, total=False):
    instance_id: str
    agent_id: str
    package_id: str
    package_version: str
    display_name: str
    config: dict[str, Any]
    secret_refs: dict[str, str]
    state: str
    generation: int
    enabled: bool
    created_at: str
    updated_at: str


class SessionRecord(TypedDict, total=False):
    id: str
    session_id: str
    agent_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    last_message_at: str | None


class SessionMessageRecord(TypedDict, total=False):
    message_id: str
    session_id: str
    role: str
    content: str
    metadata: dict[str, Any]
    created_at: str
