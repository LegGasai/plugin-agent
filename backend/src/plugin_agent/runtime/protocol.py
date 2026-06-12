from __future__ import annotations


class HostMethod:
    PREFIX = "host."
    INVOKE = "host.invoke"
    STREAM = "host.stream"
    STREAM_EVENT = "host.stream.event"
    COLLECT_TOOL_DEFINITIONS = "host.collect_tool_definitions"
    CAPABILITY_HAS = "host.capability.has"
    SCHEMA_GET = "host.schema.get"
    SCHEMA_VALIDATE = "host.schema.validate"
    SCHEMA_REGISTER = "host.schema.register"


class PluginMethod:
    CREATE_INSTANCE = "plugin.create_instance"
    START = "plugin.start"
    AFTER_START_ALL = "plugin.after_start_all"
    DESCRIBE = "plugin.describe"
    INVOKE = "plugin.invoke"
    STREAM = "plugin.stream"
    STREAM_EVENT = "plugin.stream.event"
    STOP_INSTANCE = "plugin.stop_instance"


class WorkerMethod:
    SHUTDOWN = "worker.shutdown"
