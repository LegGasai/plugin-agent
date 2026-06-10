from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from plugin_agent.models.records import AgentRecord, PluginInstanceRecord, SessionMessageRecord, SessionRecord
from plugin_agent.stores.secret_store import SecretStore
from plugin_agent.utils.time import now_iso
from plugin_agent.utils.versions import latest_version, select_default_package
from plugin_agent_sdk import PluginPackage


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
            rows = conn.execute("select package_json, updated_at from plugin_packages order by package_id, version").fetchall()
        packages = []
        for row in rows:
            package = json.loads(row["package_json"])
            package["updated_at"] = row["updated_at"]
            packages.append(package)
        return packages

    def get_package(self, package_id: str, version: str | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            if version:
                row = conn.execute(
                    "select package_json, updated_at from plugin_packages where package_id=? and version=?",
                    (package_id, version),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown plugin package: {package_id}@{version}")
                package = json.loads(row["package_json"])
                package["updated_at"] = row["updated_at"]
                return package
            rows = conn.execute("select package_json, updated_at from plugin_packages where package_id=?", (package_id,)).fetchall()
        if not rows:
            raise KeyError(f"unknown plugin package: {package_id}")
        packages = []
        for row in rows:
            package = json.loads(row["package_json"])
            package["updated_at"] = row["updated_at"]
            packages.append(package)
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

    def create_agent(self, agent: AgentRecord, instances: list[PluginInstanceRecord]) -> None:
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
                self._insert_plugin_instance(conn, instance)

    def list_agents(self) -> list[AgentRecord]:
        with self.connect() as conn:
            return [self._row_to_agent(row) for row in conn.execute("select * from agents order by created_at").fetchall()]

    def get_agent(self, agent_id: str) -> AgentRecord:
        with self.connect() as conn:
            row = conn.execute("select * from agents where agent_id=?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown agent: {agent_id}")
        return self._row_to_agent(row)

    def update_agent(self, agent_id: str, name: str | None = None, description: str | None = None) -> AgentRecord:
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

    def replace_agent_instances(
        self,
        agent_id: str,
        instances: list[PluginInstanceRecord],
        entry_loop_instance_id: str | None,
        capability_bindings: dict[str, str],
    ) -> AgentRecord:
        self.get_agent(agent_id)
        updated_at = now_iso()
        with self.connect() as conn:
            conn.execute("delete from plugin_instances where agent_id=?", (agent_id,))
            for instance in instances:
                self._insert_plugin_instance(conn, instance)
            conn.execute(
                """
                update agents
                set entry_loop_instance_id=?, capability_bindings_json=?, updated_at=?
                where agent_id=?
                """,
                (
                    entry_loop_instance_id,
                    json.dumps(capability_bindings, ensure_ascii=False),
                    updated_at,
                    agent_id,
                ),
            )
        return self.get_agent(agent_id)

    def update_agent_capability_bindings(self, agent_id: str, capability_bindings: dict[str, str]) -> AgentRecord:
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

    def create_session(self, agent_id: str, title: str | None = None) -> SessionRecord:
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

    def list_sessions(self, agent_id: str) -> list[SessionRecord]:
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

    def get_session(self, session_id: str) -> SessionRecord:
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

    def list_session_messages(self, session_id: str) -> list[SessionMessageRecord]:
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
    ) -> SessionMessageRecord:
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

    def list_instances(self, agent_id: str) -> list[PluginInstanceRecord]:
        with self.connect() as conn:
            rows = conn.execute("select * from plugin_instances where agent_id=? order by created_at", (agent_id,)).fetchall()
        return [self._row_to_instance(row) for row in rows]

    def get_instance(self, instance_id: str) -> PluginInstanceRecord:
        with self.connect() as conn:
            row = conn.execute("select * from plugin_instances where instance_id=?", (instance_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown plugin instance: {instance_id}")
        return self._row_to_instance(row)

    def update_instance_config(self, instance_id: str, config: dict[str, Any], secret_refs: dict[str, str]) -> PluginInstanceRecord:
        updated_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                "update plugin_instances set config_json=?, secret_refs_json=?, updated_at=? where instance_id=?",
                (json.dumps(config, ensure_ascii=False), json.dumps(secret_refs, ensure_ascii=False), updated_at, instance_id),
            )
        return self.get_instance(instance_id)

    def restart_instance(self, instance_id: str) -> PluginInstanceRecord:
        updated_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                "update plugin_instances set generation=generation+1, state='active', updated_at=? where instance_id=?",
                (updated_at, instance_id),
            )
        return self.get_instance(instance_id)

    def _row_to_agent(self, row: sqlite3.Row) -> AgentRecord:
        data = dict(row)
        data["capability_bindings"] = json.loads(data.pop("capability_bindings_json") or "{}")
        return data

    def _row_to_instance(self, row: sqlite3.Row) -> PluginInstanceRecord:
        data = dict(row)
        data.setdefault("package_version", "1.0.0")
        data["config"] = json.loads(data.pop("config_json"))
        data["secret_refs"] = json.loads(data.pop("secret_refs_json"))
        data["enabled"] = bool(data["enabled"])
        return data

    def _insert_plugin_instance(self, conn: sqlite3.Connection, instance: PluginInstanceRecord) -> None:
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

    def _row_to_session_message(self, row: sqlite3.Row) -> SessionMessageRecord:
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        return data

    def _describe_session(self, session: dict[str, Any]) -> SessionRecord:
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
