from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from jsonschema import ValidationError, validate
from packaging.version import InvalidVersion, Version
from plugin_agent_sdk import PluginPackage
from plugin_agent.kernel import AgentKernel, PluginBase
from plugin_agent.plugin_store import (
    copy_package_to_market,
    discover_installed_packages,
    discover_market_packages,
    install_market_package,
    load_installed_plugin_class,
    validate_plugin_package,
)
from plugin_agent.plugins.agent_loop_react.plugin import ReactAgentLoopPlugin
from plugin_agent.plugins.mcp_bridge_plugin.plugin import MCPBridgePlugin
from plugin_agent.plugins.memory_file.plugin import FileMemoryPlugin
from plugin_agent.plugins.model_deepseek.plugin import DeepSeekModelPlugin
from plugin_agent.plugins.model_openai_compatible.plugin import OpenAICompatibleModelPlugin
from plugin_agent.plugins.model_openrouter.plugin import OpenRouterModelPlugin
from plugin_agent.plugins.skill_registry.plugin import SkillRegistryPlugin
from plugin_agent.plugins.tool_basic.plugin import BasicToolPlugin
from plugin_agent.plugins.tool_runtime_plugin.plugin import ToolRuntimePlugin

PluginFactory = Callable[..., PluginBase]

DEFAULT_AGENT_PLUGIN_IDS = [
    "memory.file",
    "skill.registry",
    "model.openai_compatible",
    "tool.runtime",
    "tool.basic",
    "mcp.bridge",
    "agent.loop.react",
]

PLUGIN_FACTORIES: dict[str, PluginFactory] = {
    "memory.file": FileMemoryPlugin,
    "skill.registry": SkillRegistryPlugin,
    "model.openai_compatible": OpenAICompatibleModelPlugin,
    "model.openrouter": OpenRouterModelPlugin,
    "model.deepseek": DeepSeekModelPlugin,
    "tool.runtime": ToolRuntimePlugin,
    "tool.basic": BasicToolPlugin,
    "mcp.bridge": MCPBridgePlugin,
    "agent.loop.react": ReactAgentLoopPlugin,
}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def collect_encrypted_paths(schema: dict[str, Any], prefix: str = "") -> set[str]:
    encrypted: set[str] = set()
    if schema.get("x-encrypted") is True or schema.get("x-secret") is True:
        if prefix:
            encrypted.add(prefix)
    for key, child in (schema.get("properties") or {}).items():
        if isinstance(child, dict):
            path = f"{prefix}.{key}" if prefix else key
            encrypted.update(collect_encrypted_paths(child, path))
    return encrypted


def redact_config(config: dict[str, Any], encrypted_paths: set[str], prefix: str = "") -> dict[str, Any]:
    redacted = {}
    for key, value in config.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            redacted[key] = redact_config(value, encrypted_paths, path)
        elif path in encrypted_paths:
            redacted[key] = "********" if value else None
        else:
            redacted[key] = value
    return redacted


def version_sort_key(version: str) -> tuple[int, Any]:
    try:
        return (1, Version(str(version)))
    except InvalidVersion:
        return (0, str(version))


def latest_version(versions: list[str]) -> str:
    return max((str(version) for version in versions), key=version_sort_key)


def select_default_package(packages: list[dict[str, Any]]) -> dict[str, Any]:
    installed = [package for package in packages if package.get("source") == "installed"]
    candidates = installed or packages
    return max(candidates, key=lambda package: version_sort_key(str(package.get("version", "1.0.0"))))


class SecretStore:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.key_path = runtime_dir / "secret.key"
        if not self.key_path.exists():
            self.key_path.write_text(uuid4().hex)
        self.key = hashlib.sha256(self.key_path.read_text().encode("utf-8")).digest()

    def encrypt(self, value: str) -> str:
        raw = value.encode("utf-8")
        encrypted = bytes(byte ^ self.key[index % len(self.key)] for index, byte in enumerate(raw))
        return base64.urlsafe_b64encode(encrypted).decode("ascii")

    def decrypt(self, value: str) -> str:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        decrypted = bytes(byte ^ self.key[index % len(self.key)] for index, byte in enumerate(raw))
        return decrypted.decode("utf-8")


class ProductStore:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.db_path = runtime_dir / "product.sqlite3"
        self.secret_store = SecretStore(runtime_dir)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists plugin_packages (
                    package_id text not null,
                    version text not null,
                    package_json text not null,
                    updated_at text not null,
                    primary key(package_id, version)
                );
                create table if not exists agents (
                    agent_id text primary key,
                    name text not null,
                    description text not null,
                    entry_loop_instance_id text,
                    capability_bindings_json text not null default '{}',
                    status text not null,
                    created_at text not null,
                    updated_at text not null
                );
                create table if not exists plugin_instances (
                    instance_id text primary key,
                    agent_id text not null,
                    package_id text not null,
                    package_version text not null default '1.0.0',
                    display_name text not null,
                    config_json text not null,
                    secret_refs_json text not null,
                    state text not null,
                    generation integer not null,
                    enabled integer not null,
                    created_at text not null,
                    updated_at text not null
                );
                create table if not exists secrets (
                    secret_id text primary key,
                    ciphertext text not null,
                    created_at text not null
                );
                create table if not exists invocation_events (
                    event_id text primary key,
                    agent_id text,
                    caller_instance_id text,
                    capability text not null,
                    provider_instance_id text,
                    status text not null,
                    duration_ms integer,
                    created_at text not null
                );
                create table if not exists sessions (
                    session_id text primary key,
                    agent_id text not null,
                    title text not null,
                    status text not null,
                    created_at text not null,
                    updated_at text not null,
                    last_message_at text
                );
                create table if not exists session_messages (
                    message_id text primary key,
                    session_id text not null,
                    role text not null,
                    content text not null,
                    metadata_json text not null,
                    created_at text not null
                );
                create index if not exists idx_sessions_agent_updated on sessions(agent_id, updated_at);
                create index if not exists idx_session_messages_session_created on session_messages(session_id, created_at);
                """
            )
            self._migrate_plugin_packages_table(conn)
            agent_columns = {
                row["name"]
                for row in conn.execute("pragma table_info(agents)").fetchall()
            }
            if "capability_bindings_json" not in agent_columns:
                conn.execute("alter table agents add column capability_bindings_json text not null default '{}'")
            instance_columns = {
                row["name"]
                for row in conn.execute("pragma table_info(plugin_instances)").fetchall()
            }
            if "package_version" not in instance_columns:
                conn.execute("alter table plugin_instances add column package_version text not null default '1.0.0'")
                self._pin_existing_instance_versions(conn)

    def _migrate_plugin_packages_table(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("pragma table_info(plugin_packages)").fetchall()
        }
        if "version" in columns:
            return
        rows = conn.execute("select package_id, package_json, updated_at from plugin_packages").fetchall()
        conn.execute("alter table plugin_packages rename to plugin_packages_legacy")
        conn.execute(
            """
            create table plugin_packages (
                package_id text not null,
                version text not null,
                package_json text not null,
                updated_at text not null,
                primary key(package_id, version)
            )
            """
        )
        for row in rows:
            package = json.loads(row["package_json"])
            version = str(package.get("version", "1.0.0"))
            conn.execute(
                "insert or replace into plugin_packages(package_id, version, package_json, updated_at) values (?, ?, ?, ?)",
                (row["package_id"], version, row["package_json"], row["updated_at"]),
            )
        conn.execute("drop table plugin_packages_legacy")

    def _pin_existing_instance_versions(self, conn: sqlite3.Connection) -> None:
        package_versions: dict[str, list[str]] = {}
        rows = conn.execute("select package_id, version from plugin_packages").fetchall()
        for row in rows:
            package_versions.setdefault(row["package_id"], []).append(str(row["version"]))
        for package_id, versions in package_versions.items():
            selected = latest_version(versions)
            conn.execute(
                "update plugin_instances set package_version=? where package_id=? and package_version='1.0.0'",
                (selected, package_id),
            )

    def upsert_package(self, package: PluginPackage) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into plugin_packages(package_id, version, package_json, updated_at)
                values (?, ?, ?, ?)
                on conflict(package_id, version) do update set package_json=excluded.package_json, updated_at=excluded.updated_at
                """,
                (package.package_id, package.version, json.dumps(package.model_dump(), ensure_ascii=False), now_iso()),
            )

    def list_packages(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select package_json from plugin_packages order by package_id, version").fetchall()
        return [json.loads(row["package_json"]) for row in rows]

    def get_package(self, package_id: str, version: str | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            if version:
                row = conn.execute(
                    "select package_json from plugin_packages where package_id=? and version=?",
                    (package_id, version),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown plugin package: {package_id}@{version}")
                return json.loads(row["package_json"])
            rows = conn.execute("select package_json from plugin_packages where package_id=?", (package_id,)).fetchall()
        if not rows:
            raise KeyError(f"unknown plugin package: {package_id}")
        packages = [json.loads(row["package_json"]) for row in rows]
        return select_default_package(packages)

    def delete_package(self, package_id: str, version: str | None = None) -> None:
        with self.connect() as conn:
            if version:
                conn.execute("delete from plugin_packages where package_id=? and version=?", (package_id, version))
            else:
                conn.execute("delete from plugin_packages where package_id=?", (package_id,))

    def count_instances_for_package(self, package_id: str, version: str | None = None) -> int:
        with self.connect() as conn:
            if version:
                row = conn.execute(
                    "select count(*) as count from plugin_instances where package_id=? and package_version=?",
                    (package_id, version),
                ).fetchone()
            else:
                row = conn.execute("select count(*) as count from plugin_instances where package_id=?", (package_id,)).fetchone()
        return int(row["count"] if row else 0)

    def save_secret(self, value: str) -> str:
        secret_id = f"secret-{uuid4().hex[:12]}"
        with self.connect() as conn:
            conn.execute(
                "insert into secrets(secret_id, ciphertext, created_at) values (?, ?, ?)",
                (secret_id, self.secret_store.encrypt(value), now_iso()),
            )
        return secret_id

    def read_secret(self, secret_id: str) -> str:
        with self.connect() as conn:
            row = conn.execute("select ciphertext from secrets where secret_id=?", (secret_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown secret: {secret_id}")
        return self.secret_store.decrypt(row["ciphertext"])

    def create_agent(self, agent: dict[str, Any], instances: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into agents(
                    agent_id, name, description, entry_loop_instance_id, capability_bindings_json,
                    status, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent["agent_id"],
                    agent["name"],
                    agent["description"],
                    agent.get("entry_loop_instance_id"),
                    json.dumps(agent.get("capability_bindings", {}), ensure_ascii=False),
                    agent["status"],
                    agent["created_at"],
                    agent["updated_at"],
                ),
            )
            for instance in instances:
                conn.execute(
                    """
                    insert into plugin_instances(
                        instance_id, agent_id, package_id, package_version, display_name, config_json, secret_refs_json,
                        state, generation, enabled, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        instance["instance_id"],
                        instance["agent_id"],
                        instance["package_id"],
                        instance["package_version"],
                        instance["display_name"],
                        json.dumps(instance["config"], ensure_ascii=False),
                        json.dumps(instance["secret_refs"], ensure_ascii=False),
                        instance["state"],
                        instance["generation"],
                        1 if instance["enabled"] else 0,
                        instance["created_at"],
                        instance["updated_at"],
                    ),
                )

    def list_agents(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [self._row_to_agent(row) for row in conn.execute("select * from agents order by created_at").fetchall()]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("select * from agents where agent_id=?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown agent: {agent_id}")
        return self._row_to_agent(row)

    def update_agent(self, agent_id: str, name: str | None = None, description: str | None = None) -> dict[str, Any]:
        current = self.get_agent(agent_id)
        next_name = current["name"] if name is None else name.strip()
        if not next_name:
            raise ValueError("agent name is required")
        next_description = current.get("description", "") if description is None else description.strip()
        updated_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                "update agents set name=?, description=?, updated_at=? where agent_id=?",
                (next_name, next_description, updated_at, agent_id),
            )
        return self.get_agent(agent_id)

    def update_agent_capability_bindings(self, agent_id: str, capability_bindings: dict[str, str]) -> dict[str, Any]:
        self.get_agent(agent_id)
        if not isinstance(capability_bindings, dict):
            raise ValueError("capability_bindings must be an object")
        normalized = {}
        for capability, provider_instance_id in capability_bindings.items():
            if not isinstance(capability, str) or not capability.strip():
                raise ValueError("capability binding names must be non-empty strings")
            if not isinstance(provider_instance_id, str) or not provider_instance_id.strip():
                raise ValueError("capability binding provider ids must be non-empty strings")
            normalized[capability.strip()] = provider_instance_id.strip()
        updated_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                "update agents set capability_bindings_json=?, updated_at=? where agent_id=?",
                (json.dumps(normalized, ensure_ascii=False), updated_at, agent_id),
            )
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("select agent_id from agents where agent_id=?", (agent_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown agent: {agent_id}")
            session_rows = conn.execute("select session_id from sessions where agent_id=?", (agent_id,)).fetchall()
            for session in session_rows:
                conn.execute("delete from session_messages where session_id=?", (session["session_id"],))
            conn.execute("delete from sessions where agent_id=?", (agent_id,))
            conn.execute("delete from plugin_instances where agent_id=?", (agent_id,))
            conn.execute("delete from agents where agent_id=?", (agent_id,))
        return True

    def create_session(self, agent_id: str, title: str | None = None) -> dict[str, Any]:
        self.get_agent(agent_id)
        stamp = now_iso()
        session = {
            "session_id": f"session-{uuid4().hex[:12]}",
            "agent_id": agent_id,
            "title": (title or "新会话").strip() or "新会话",
            "status": "active",
            "created_at": stamp,
            "updated_at": stamp,
            "last_message_at": None,
        }
        with self.connect() as conn:
            conn.execute(
                """
                insert into sessions(session_id, agent_id, title, status, created_at, updated_at, last_message_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    session["agent_id"],
                    session["title"],
                    session["status"],
                    session["created_at"],
                    session["updated_at"],
                    session["last_message_at"],
                ),
            )
        return self._describe_session(session)

    def list_sessions(self, agent_id: str) -> list[dict[str, Any]]:
        self.get_agent(agent_id)
        with self.connect() as conn:
            rows = conn.execute(
                """
                select * from sessions
                where agent_id=?
                order by coalesce(last_message_at, updated_at) desc, created_at desc
                """,
                (agent_id,),
            ).fetchall()
        return [self._describe_session(dict(row)) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("select * from sessions where session_id=?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown session: {session_id}")
        return self._describe_session(dict(row))

    def delete_session(self, session_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("select session_id from sessions where session_id=?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown session: {session_id}")
            conn.execute("delete from session_messages where session_id=?", (session_id,))
            conn.execute("delete from sessions where session_id=?", (session_id,))
        return True

    def list_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        self.get_session(session_id)
        with self.connect() as conn:
            rows = conn.execute(
                "select * from session_messages where session_id=? order by created_at",
                (session_id,),
            ).fetchall()
        return [self._row_to_session_message(row) for row in rows]

    def append_session_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self.get_session(session_id)
        stamp = now_iso()
        message = {
            "message_id": f"msg-{uuid4().hex[:12]}",
            "session_id": session_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_at": stamp,
        }
        next_title = session["title"]
        existing_messages = self.list_session_messages(session_id)
        if role == "user" and (not existing_messages or session["title"] == "新会话"):
            next_title = self._session_title_from_message(content)
        with self.connect() as conn:
            conn.execute(
                """
                insert into session_messages(message_id, session_id, role, content, metadata_json, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    message["message_id"],
                    message["session_id"],
                    message["role"],
                    message["content"],
                    json.dumps(message["metadata"], ensure_ascii=False),
                    message["created_at"],
                ),
            )
            conn.execute(
                "update sessions set title=?, updated_at=?, last_message_at=? where session_id=?",
                (next_title, stamp, stamp, session_id),
            )
        return message

    def list_instances(self, agent_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from plugin_instances where agent_id=? order by created_at", (agent_id,)).fetchall()
        return [self._row_to_instance(row) for row in rows]

    def get_instance(self, instance_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("select * from plugin_instances where instance_id=?", (instance_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown plugin instance: {instance_id}")
        return self._row_to_instance(row)

    def update_instance_config(self, instance_id: str, config: dict[str, Any], secret_refs: dict[str, str]) -> dict[str, Any]:
        updated_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                "update plugin_instances set config_json=?, secret_refs_json=?, updated_at=? where instance_id=?",
                (json.dumps(config, ensure_ascii=False), json.dumps(secret_refs, ensure_ascii=False), updated_at, instance_id),
            )
        return self.get_instance(instance_id)

    def restart_instance(self, instance_id: str) -> dict[str, Any]:
        updated_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                "update plugin_instances set generation=generation+1, state='active', updated_at=? where instance_id=?",
                (updated_at, instance_id),
            )
        return self.get_instance(instance_id)

    def _row_to_agent(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["capability_bindings"] = json.loads(data.pop("capability_bindings_json") or "{}")
        return data

    def _row_to_instance(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data.setdefault("package_version", "1.0.0")
        data["config"] = json.loads(data.pop("config_json"))
        data["secret_refs"] = json.loads(data.pop("secret_refs_json"))
        data["enabled"] = bool(data["enabled"])
        return data

    def _row_to_session_message(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        return data

    def _describe_session(self, session: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": session["session_id"],
            "session_id": session["session_id"],
            "agent_id": session["agent_id"],
            "title": session["title"],
            "status": session["status"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "last_message_at": session.get("last_message_at"),
        }

    def _session_title_from_message(self, content: str) -> str:
        compact = " ".join(content.strip().split())
        if not compact:
            return "新会话"
        return compact[:32]


def default_market_dir() -> Path:
    configured = os.getenv("PLUGIN_AGENT_MARKET_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[3] / "plugin-market"


class AgentAssemblyService:
    def __init__(self, runtime_dir: str | Path | None = None, market_dir: str | Path | None = None) -> None:
        self.runtime_dir = Path(runtime_dir or ".plugin-agent").expanduser()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.market_dir = Path(market_dir).expanduser() if market_dir else default_market_dir()
        self.installed_plugins_dir = self.runtime_dir / "installed-plugins"
        self.store = ProductStore(self.runtime_dir)
        self.plugin_config_overrides: dict[str, dict[str, Any]] = {}
        self.refresh_plugin_packages()

    def refresh_plugin_packages(self) -> dict[str, Any]:
        for package_id in sorted(PLUGIN_FACTORIES):
            plugin = self.instantiate_plugin(package_id)
            self.store.upsert_package(plugin.package_model())
        for package in discover_installed_packages(self.installed_plugins_dir):
            self.store.upsert_package(package)
        for package in self.store.list_packages():
            if package.get("source") == "builtin" and package["package_id"] not in PLUGIN_FACTORIES:
                self.store.delete_package(package["package_id"], package.get("version", "1.0.0"))
        return {"plugin_packages": self.list_plugin_packages()}

    def list_plugin_packages(self, tag: str | None = None) -> list[dict[str, Any]]:
        packages = self.store.list_packages()
        if tag:
            packages = [package for package in packages if tag in package.get("tags", [])]
        return packages

    def list_installed_plugin_packages(self, tag: str | None = None) -> list[dict[str, Any]]:
        return self.list_plugin_packages(tag=tag)

    def list_market_plugin_packages(self, tag: str | None = None) -> list[dict[str, Any]]:
        installed_keys = {
            (package["package_id"], package.get("version", "1.0.0"))
            for package in self.list_installed_plugin_packages()
        }
        market_packages = []
        for package in discover_market_packages(self.market_dir):
            if tag and tag not in package.tags:
                continue
            data = package.model_dump()
            data["installed"] = (package.package_id, package.version) in installed_keys
            market_packages.append(data)
        return market_packages

    def list_plugin_catalog(self) -> list[dict[str, Any]]:
        plugins = []
        for package in self.list_plugin_packages():
            plugin = self.instantiate_plugin(package["package_id"], package_version=package.get("version"))
            plugins.append(self.describe_plugin(plugin, enabled=package["package_id"] in DEFAULT_AGENT_PLUGIN_IDS))
        return plugins

    def marketplace(self, tag: str | None = None) -> dict[str, Any]:
        market_packages = self.list_market_plugin_packages(tag=tag)
        return {
            "plugin_packages": market_packages,
            "market_plugin_packages": market_packages,
            "market_dir": str(self.market_dir),
            "upload": {"available": True, "implemented": True, "message": "Upload a .pluginpkg file or plugin directory path."},
        }

    def reserve_upload(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = payload.get("path")
        if not path:
            raise ValueError("path is required")
        package, market_path = copy_package_to_market(path, self.market_dir)
        return {"plugin_package": package.model_dump(), "market_path": str(market_path)}

    def install_market_plugin(self, payload: dict[str, Any]) -> dict[str, Any]:
        package_id = payload.get("package_id")
        if not package_id:
            raise ValueError("package_id is required")
        version = payload.get("version")
        market_package = self._find_market_package(package_id, version)
        package, installed_path = install_market_package(Path(market_package.market_path or ""), self.installed_plugins_dir)
        self.store.upsert_package(package)
        return {"plugin_package": package.model_dump(), "installed_path": str(installed_path)}

    def uninstall_installed_plugin(self, package_id: str, version: str | None = None) -> dict[str, Any]:
        package = self.store.get_package(package_id, version)
        version = str(package.get("version", "1.0.0"))
        if package.get("source") != "installed":
            raise ValueError("only installed external plugin packages can be uninstalled")
        usage_count = self.store.count_instances_for_package(package_id, version)
        if usage_count:
            raise ValueError(f"plugin package is used by {usage_count} plugin instance(s)")

        installed_path = package.get("installed_path")
        if installed_path:
            path = Path(installed_path).expanduser().resolve()
            installed_root = self.installed_plugins_dir.resolve()
            if path.exists() and path.is_relative_to(installed_root):
                shutil.rmtree(path)

        self.store.delete_package(package_id, version)
        if package_id in PLUGIN_FACTORIES:
            self.store.upsert_package(self.instantiate_plugin(package_id).package_model())
        return {"plugin_package": package, "uninstalled": True}

    def validate_plugin(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = payload.get("path")
        if not path:
            raise ValueError("path is required")
        return validate_plugin_package(path)

    def create_agent(
        self,
        name: str,
        plugin_ids: list[str] | None = None,
        configs: dict[str, dict[str, Any]] | None = None,
        description: str = "",
        plugin_instances: list[dict[str, Any]] | None = None,
        capability_bindings: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        agent_id = f"agent-{uuid4().hex[:10]}"
        specs = plugin_instances or [{"package_id": plugin_id, "config": (configs or {}).get(plugin_id, {})} for plugin_id in (plugin_ids or DEFAULT_AGENT_PLUGIN_IDS)]
        instances = [self._create_instance_record(agent_id, spec) for spec in specs]
        entry_loop = self._find_entry_loop(instances)
        stamp = now_iso()
        agent = {
            "agent_id": agent_id,
            "name": name,
            "description": description,
            "entry_loop_instance_id": entry_loop["instance_id"] if entry_loop else None,
            "capability_bindings": capability_bindings or {},
            "status": "active",
            "created_at": stamp,
            "updated_at": stamp,
        }
        self.store.create_agent(agent, instances)
        return self._describe_agent(agent, instances)

    def list_agents(self) -> list[dict[str, Any]]:
        return [self._describe_agent(agent, self.store.list_instances(agent["agent_id"])) for agent in self.store.list_agents()]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        agent = self.store.get_agent(agent_id)
        return self._describe_agent(agent, self.store.list_instances(agent_id))

    def update_agent(self, agent_id: str, name: str | None = None, description: str | None = None) -> dict[str, Any]:
        agent = self.store.update_agent(agent_id, name=name, description=description)
        return self._describe_agent(agent, self.store.list_instances(agent_id))

    def update_agent_capability_bindings(self, agent_id: str, capability_bindings: dict[str, str]) -> dict[str, Any]:
        self._validate_capability_bindings(agent_id, capability_bindings)
        agent = self.store.update_agent_capability_bindings(agent_id, capability_bindings)
        return self._describe_agent(agent, self.store.list_instances(agent_id))

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        self.store.delete_agent(agent_id)
        return {"deleted": True, "agent_id": agent_id}

    def create_session(self, agent_id: str, title: str | None = None) -> dict[str, Any]:
        return self.store.create_session(agent_id, title)

    def list_sessions(self, agent_id: str) -> list[dict[str, Any]]:
        return self.store.list_sessions(agent_id)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.store.get_session(session_id)

    def delete_session(self, session_id: str) -> dict[str, Any]:
        self.store.delete_session(session_id)
        return {"deleted": True, "session_id": session_id}

    def list_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self.store.list_session_messages(session_id)

    def agent_capabilities(self, agent_id: str) -> list[dict[str, Any]]:
        kernel = self.build_kernel_for_agent(agent_id)
        return [binding.model_dump() for binding in kernel.capability_registry.list()]

    def agent_resources(self, agent_id: str) -> list[dict[str, Any]]:
        kernel = self.build_kernel_for_agent(agent_id)
        return [resource.model_dump() for resource in kernel.resource_registry.list()]

    def agent_runtime(self, agent_id: str) -> dict[str, Any]:
        agent = self.store.get_agent(agent_id)
        instances = self.store.list_instances(agent_id)
        kernel = self._build_kernel_from_instances(
            instances,
            agent_id=agent_id,
            capability_bindings=agent.get("capability_bindings", {}),
            raise_on_failed=False,
        )
        return {
            "status": kernel.runtime_status,
            "diagnostics": [diagnostic.model_dump() for diagnostic in kernel.diagnostics],
            "capability_bindings": agent.get("capability_bindings", {}),
            "startup_order": kernel.startup_order,
            "capabilities": [binding.model_dump() for binding in kernel.capability_registry.list()],
            "capability_candidates": kernel.discover_capabilities(),
            "resources": [resource.model_dump() for resource in kernel.resource_registry.list()],
        }

    def agent_capability_candidates(self, agent_id: str) -> list[dict[str, Any]]:
        agent = self.store.get_agent(agent_id)
        instances = self.store.list_instances(agent_id)
        kernel = self._build_kernel_from_instances(
            instances,
            agent_id=agent_id,
            capability_bindings=agent.get("capability_bindings", {}),
            raise_on_failed=False,
        )
        return kernel.discover_capabilities()

    def run_saved_agent(self, agent_id: str, message: str, session_id: str | None = None) -> dict[str, Any]:
        kernel = self.build_kernel_for_agent(agent_id)
        session = self._ensure_session(agent_id, session_id)
        history = self._history_for_session(session["session_id"])
        self.store.append_session_message(session["session_id"], "user", message)
        result = kernel.invoke("agent.run", {"message": message}, {"agent_id": agent_id, "session_id": session["session_id"], "history_messages": history}).payload
        self.store.append_session_message(session["session_id"], "assistant", result.get("answer", ""), result)
        return {**result, "session_id": session["session_id"]}

    def get_plugin_config(self, plugin_id: str, redact: bool = True) -> dict[str, Any]:
        plugin = self.instantiate_plugin(plugin_id)
        config = plugin.config
        return self._redact_config_for_package(plugin_id, config) if redact else config

    def update_plugin_config(self, plugin_id: str, config: dict[str, Any]) -> dict[str, Any]:
        current = self.plugin_config_overrides.get(plugin_id, {})
        self.plugin_config_overrides[plugin_id] = deep_merge(current, config)
        plugin = self.instantiate_plugin(plugin_id)
        return self.describe_plugin(plugin, enabled=plugin_id in DEFAULT_AGENT_PLUGIN_IDS)

    def update_plugin_instance_config(self, instance_id: str, config: dict[str, Any]) -> dict[str, Any]:
        current = self.store.get_instance(instance_id)
        real_config = self._hydrate_config(current["config"], current["secret_refs"])
        encrypted_paths = self._encrypted_config_paths(current["package_id"], current.get("package_version"))
        sanitized_config = self._strip_redacted_secret_placeholders(config, encrypted_paths)
        merged = deep_merge(real_config, sanitized_config)
        self._validate_instance_config(current["package_id"], merged, current.get("package_version"))
        stored_config, secret_refs = self._split_config_secrets(merged, encrypted_paths)
        updated = self.store.update_instance_config(instance_id, stored_config, secret_refs)
        return self._describe_instance(updated)

    def restart_plugin_instance(self, instance_id: str) -> dict[str, Any]:
        return self._describe_instance(self.store.restart_instance(instance_id))

    def build_kernel_for_agent(self, agent_id: str) -> AgentKernel:
        agent = self.store.get_agent(agent_id)
        instances = self.store.list_instances(agent_id)
        return self._build_kernel_from_instances(instances, agent_id=agent_id, capability_bindings=agent.get("capability_bindings", {}))

    def build_kernel(
        self,
        plugin_ids: list[str] | None = None,
        configs: dict[str, dict[str, Any]] | None = None,
        capability_bindings: dict[str, str] | None = None,
    ) -> AgentKernel:
        instances = [
            self._create_instance_record("adhoc-agent", {"package_id": plugin_id, "config": (configs or {}).get(plugin_id, {})}, persist_secrets=False)
            for plugin_id in (plugin_ids or DEFAULT_AGENT_PLUGIN_IDS)
        ]
        return self._build_kernel_from_instances(instances, agent_id="adhoc-agent", capability_bindings=capability_bindings or {})

    def stream_agent(self, message: str, plugin_ids: list[str] | None = None, configs: dict[str, dict[str, Any]] | None = None) -> Any:
        kernel = self.build_kernel(plugin_ids, configs)
        yield from kernel.stream("agent.stream", {"message": message}, {"agent_id": "adhoc-agent"})

    def assemble(self, plugin_ids: list[str] | None = None, configs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        kernel = self.build_kernel(plugin_ids, configs)
        return self._describe_assembly(kernel)

    def run_agent(self, message: str, plugin_ids: list[str] | None = None, configs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        kernel = self.build_kernel(plugin_ids, configs)
        return kernel.invoke("agent.run", {"message": message}, {"agent_id": "adhoc-agent"}).payload

    def stream_saved_agent(self, agent_id: str, message: str, session_id: str | None = None) -> Any:
        kernel = self.build_kernel_for_agent(agent_id)
        session = self._ensure_session(agent_id, session_id)
        history = self._history_for_session(session["session_id"])
        self.store.append_session_message(session["session_id"], "user", message)
        for event in kernel.stream("agent.stream", {"message": message}, {"agent_id": agent_id, "session_id": session["session_id"], "history_messages": history}):
            if event["type"] == "run_completed":
                self.store.append_session_message(session["session_id"], "assistant", event.get("payload", {}).get("answer", ""), event.get("payload", {}))
                event = {**event, "payload": {**event.get("payload", {}), "session_id": session["session_id"]}}
            elif event["type"] == "run_failed":
                payload = event.get("payload", {})
                self.store.append_session_message(session["session_id"], "assistant", payload.get("answer") or payload.get("error") or "运行失败", payload)
                event = {**event, "payload": {**payload, "session_id": session["session_id"]}}
            yield event

    def instantiate_plugin(
        self,
        package_id: str,
        config: dict[str, Any] | None = None,
        instance_id: str | None = None,
        package_version: str | None = None,
    ) -> PluginBase:
        merged = deep_merge(self.plugin_config_overrides.get(package_id, {}), config or {})
        if package_id == "memory.file" and "path" not in merged:
            merged["path"] = str(self.runtime_dir / "memory.jsonl")
        try:
            package = self.store.get_package(package_id, package_version)
        except KeyError:
            package = None
        if package and package.get("source") == "installed":
            installed_path = package.get("installed_path")
            entrypoint = package.get("entrypoint")
            if not installed_path or not entrypoint:
                raise KeyError(f"installed plugin package is missing runtime entrypoint: {package_id}")
            plugin_class = load_installed_plugin_class(installed_path, entrypoint)
            return plugin_class(merged or None, instance_id=instance_id)
        if package_id in PLUGIN_FACTORIES:
            return PLUGIN_FACTORIES[package_id](merged or None, instance_id=instance_id)
        package = package or self.store.get_package(package_id, package_version)
        installed_path = package.get("installed_path")
        entrypoint = package.get("entrypoint")
        if not installed_path or not entrypoint:
            raise KeyError(f"unknown plugin package: {package_id}")
        plugin_class = load_installed_plugin_class(installed_path, entrypoint)
        return plugin_class(merged or None, instance_id=instance_id)

    def describe_plugin(self, plugin: PluginBase, enabled: bool) -> dict[str, Any]:
        package = plugin.package_model()
        return {
            "id": plugin.package_id,
            "package_id": plugin.package_id,
            "name": package.name,
            "version": package.version,
            "state": plugin.state.value,
            "enabled": enabled,
            "config": self._redact_config_for_package(plugin.package_id, plugin.config),
            "requires": [dep.model_dump() for dep in plugin.descriptor_model.requires],
            "provides": [cap.model_dump() for cap in plugin.descriptor_model.provides],
            "resources": [resource.model_dump() for resource in plugin.resource_specs],
            "tags": package.tags,
            "config_schema_ref": package.config_schema_ref,
            "schemas": [schema.model_dump() for schema in package.schemas],
            "manifest_path": str(plugin.manifest_path),
        }

    def _build_kernel_from_instances(
        self,
        instances: list[dict[str, Any]],
        agent_id: str,
        capability_bindings: dict[str, str] | None = None,
        raise_on_failed: bool = True,
    ) -> AgentKernel:
        kernel = AgentKernel(capability_bindings=capability_bindings or {})
        plugins = []
        for instance in instances:
            config = self._hydrate_config(instance["config"], instance.get("secret_refs", {}))
            plugin = self.instantiate_plugin(
                instance["package_id"],
                config,
                instance["instance_id"],
                package_version=instance.get("package_version"),
            )
            plugin.generation = int(instance.get("generation", 1))
            plugins.append(plugin)
        kernel.load_plugins(plugins)
        kernel.start_all(raise_on_failed=raise_on_failed)
        return kernel

    def _describe_assembly(self, kernel: AgentKernel) -> dict[str, Any]:
        return {
            "status": kernel.runtime_status,
            "diagnostics": [diagnostic.model_dump() for diagnostic in kernel.diagnostics],
            "capability_bindings": kernel.capability_bindings,
            "capability_candidates": kernel.discover_capabilities(),
            "startup_order": kernel.startup_order,
            "plugins": [self.describe_plugin(plugin, enabled=True) for plugin in kernel.plugins.values()],
            "capabilities": [binding.model_dump() for binding in kernel.capability_registry.list()],
            "resources": [resource.model_dump() for resource in kernel.resource_registry.list()],
            "tools": kernel.invoke("tool.registry.list", {}).payload["tools"] if kernel.capability_registry.has("tool.registry.list") else [],
        }

    def _validate_capability_bindings(self, agent_id: str, capability_bindings: dict[str, str]) -> None:
        instances = self.store.list_instances(agent_id)
        kernel = self._build_kernel_from_instances(instances, agent_id=agent_id, capability_bindings={}, raise_on_failed=False)
        candidates_by_capability = {
            item["capability"]: {candidate["provider_instance_id"] for candidate in item["candidates"]}
            for item in kernel.discover_capabilities()
        }
        for capability, provider_instance_id in capability_bindings.items():
            candidates = candidates_by_capability.get(capability, set())
            if provider_instance_id not in candidates:
                raise ValueError(f"{capability} cannot be bound to {provider_instance_id}: provider is not installed in this Agent")

    def _create_instance_record(self, agent_id: str, spec: dict[str, Any], persist_secrets: bool = True) -> dict[str, Any]:
        package_id = spec["package_id"]
        package_version = spec.get("package_version") or spec.get("version")
        package = self.store.get_package(package_id, package_version)
        package_version = str(package.get("version", "1.0.0"))
        default_config = self._default_instance_config(package_id, package_version)
        raw_config = deep_merge(default_config, dict(spec.get("config") or {}))
        if package_id == "memory.file" and "path" not in raw_config:
            raw_config["path"] = str(self.runtime_dir / f"{agent_id}-{uuid4().hex[:8]}-memory.jsonl")
        elif package_id == "memory.file" and not (spec.get("config") or {}).get("path"):
            raw_config["path"] = str(self.runtime_dir / f"{agent_id}-{uuid4().hex[:8]}-memory.jsonl")
        self._validate_instance_config(package_id, raw_config, package_version)
        encrypted_paths = self._encrypted_config_paths(package_id, package_version)
        config, secret_refs = self._split_config_secrets(raw_config, encrypted_paths, persist=persist_secrets)
        stamp = now_iso()
        return {
            "instance_id": spec.get("instance_id") or f"pi-{uuid4().hex[:12]}",
            "agent_id": agent_id,
            "package_id": package_id,
            "package_version": package_version,
            "display_name": spec.get("display_name") or package["name"],
            "config": config,
            "secret_refs": secret_refs,
            "state": "active",
            "generation": int(spec.get("generation", 1)),
            "enabled": bool(spec.get("enabled", True)),
            "created_at": stamp,
            "updated_at": stamp,
        }

    def _find_entry_loop(self, instances: list[dict[str, Any]]) -> dict[str, Any] | None:
        for instance in instances:
            package = self.store.get_package(instance["package_id"], instance.get("package_version"))
            if any(resource["kind"] == "agent_loop" for resource in package.get("resources", [])):
                return instance
        return None

    def _ensure_session(self, agent_id: str, session_id: str | None = None) -> dict[str, Any]:
        if session_id:
            session = self.store.get_session(session_id)
            if session["agent_id"] != agent_id:
                raise ValueError("session does not belong to agent")
            return session
        return self.store.create_session(agent_id)

    def _history_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [
            {"role": message["role"], "content": message["content"], "metadata": message.get("metadata", {})}
            for message in self.store.list_session_messages(session_id)
            if message["role"] in {"user", "assistant", "tool"}
        ]

    def _describe_agent(self, agent: dict[str, Any], instances: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": agent["agent_id"],
            "name": agent["name"],
            "description": agent.get("description", ""),
            "entry_loop_instance_id": agent.get("entry_loop_instance_id"),
            "capability_bindings": agent.get("capability_bindings", {}),
            "status": agent.get("status", "active"),
            "plugin_ids": [instance["package_id"] for instance in instances],
            "plugin_instances": [self._describe_instance(instance) for instance in instances],
            "configs": {instance["package_id"]: self._describe_instance(instance)["config"] for instance in instances},
            "created_at": agent.get("created_at"),
            "updated_at": agent.get("updated_at"),
        }

    def _describe_instance(self, instance: dict[str, Any]) -> dict[str, Any]:
        config = self._hydrate_config(instance["config"], instance.get("secret_refs", {}), reveal=False)
        return {
            "instance_id": instance["instance_id"],
            "agent_id": instance["agent_id"],
            "package_id": instance["package_id"],
            "package_version": instance.get("package_version", "1.0.0"),
            "display_name": instance["display_name"],
            "config": self._redact_config_for_package(instance["package_id"], config, instance.get("package_version")),
            "config_schema_ref": self.store.get_package(instance["package_id"], instance.get("package_version")).get("config_schema_ref"),
            "secret_refs": sorted(instance.get("secret_refs", {}).keys()),
            "state": instance["state"],
            "generation": instance["generation"],
            "enabled": instance["enabled"],
            "created_at": instance["created_at"],
            "updated_at": instance["updated_at"],
        }

    def _strip_redacted_secret_placeholders(self, config: dict[str, Any], encrypted_paths: set[str], prefix: str = "") -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in config.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                child = self._strip_redacted_secret_placeholders(value, encrypted_paths, path)
                if child or path not in encrypted_paths:
                    clean[key] = child
            elif path in encrypted_paths and value == "********":
                continue
            else:
                clean[key] = value
        return clean

    def _split_config_secrets(self, config: dict[str, Any], encrypted_paths: set[str], persist: bool = True, prefix: str = "") -> tuple[dict[str, Any], dict[str, str]]:
        clean: dict[str, Any] = {}
        refs: dict[str, str] = {}
        for key, value in config.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                child_config, child_refs = self._split_config_secrets(value, encrypted_paths, persist=persist, prefix=path)
                clean[key] = child_config
                refs.update(child_refs)
            elif path in encrypted_paths and value:
                if persist:
                    refs[path] = self.store.save_secret(str(value))
                else:
                    clean[key] = value
            else:
                clean[key] = value
        return clean, refs

    def _hydrate_config(self, config: dict[str, Any], secret_refs: dict[str, str], reveal: bool = True) -> dict[str, Any]:
        hydrated = json.loads(json.dumps(config))
        for path, secret_id in secret_refs.items():
            target = hydrated
            parts = path.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = self.store.read_secret(secret_id) if reveal else "********"
        return hydrated

    def _default_instance_config(self, package_id: str, package_version: str | None = None) -> dict[str, Any]:
        return json.loads(json.dumps(self.instantiate_plugin(package_id, package_version=package_version).config))

    def _config_schema_for_package(self, package_id: str, package_version: str | None = None) -> dict[str, Any] | None:
        package = self.store.get_package(package_id, package_version)
        schema_ref = package.get("config_schema_ref")
        if not schema_ref:
            return None
        for schema in package.get("schemas", []):
            if schema.get("schema_ref") == schema_ref:
                return schema.get("json_schema") or {}
        return None

    def _encrypted_config_paths(self, package_id: str, package_version: str | None = None) -> set[str]:
        schema = self._config_schema_for_package(package_id, package_version)
        return collect_encrypted_paths(schema or {})

    def _redact_config_for_package(self, package_id: str, config: dict[str, Any], package_version: str | None = None) -> dict[str, Any]:
        return redact_config(config, self._encrypted_config_paths(package_id, package_version))

    def _validate_instance_config(self, package_id: str, config: dict[str, Any], package_version: str | None = None) -> None:
        schema = self._config_schema_for_package(package_id, package_version)
        if not schema:
            return
        try:
            validate(instance=config, schema=schema)
        except ValidationError as exc:
            path = ".".join(str(part) for part in exc.path) or "config"
            raise ValueError(f"{package_id} config validation failed at {path}: {exc.message}") from exc

    def _find_market_package(self, package_id: str, version: str | None = None) -> PluginPackage:
        matches = [
            package
            for package in discover_market_packages(self.market_dir)
            if package.package_id == package_id and (version is None or package.version == version)
        ]
        if not matches:
            raise KeyError(f"unknown market plugin package: {package_id}")
        return matches[-1]
