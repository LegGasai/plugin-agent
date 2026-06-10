# plugin-agent backend

Python backend for the pluginized Agent platform.

## What Works

- Product model:
  - `PluginPackage`: static plugin package discovered from local plugin folders.
  - `PluginInstance`: per-Agent plugin installation with an explicit package version, independent config, secret refs, lifecycle state, and generation.
  - `Agent`: saved assembly of plugin instances with one Agent Loop entry.
  - `Session`: host-owned chat thread for one Agent, with persisted messages.
- SQLite persistence for agents, sessions, session messages, plugin instances, local plugin package index, local secret refs, and invocation-event table scaffolding.
- Resource registry for discoverable semantic resources such as `agent_loop`, `model`, `memory`, `skill`, `tool`, `context`, and `mcp_server`.
- Streaming Agent runs through plugin capabilities: `Plugin.stream()`, `AgentKernel.stream()`, `agent.stream`, `model.chat.stream`, and HTTP SSE.
- Runtime diagnostics and discovery for Agent assembly, including capability candidates, dependency status, provider conflicts, explicit capability bindings, and startup order.
- Runtime diagnostics include plugin startup failures such as missing required provider config.
- ReAct Agent Loop receives current session history from the host runtime, loads recent plugin memory into the model context before each run, applies configured tool-call timeouts, and writes the user message, assistant answer, and tool traces back to memory.
- Local plugin marketplace simulation:
  - The frontend marketplace upload flow accepts plugin directories or `.pluginpkg` files.
  - `plugin-market/` stores uploaded marketplace packages internally during local development.
  - `.plugin-agent/installed-plugins/` stores installed plugin packages by `package_id/version`.
  - `GET /api/marketplace/plugins` lists marketplace packages; `GET /api/installed-plugin-packages` lists installed and built-in packages available for Agent assembly.
  - Agent assembly can load both built-in plugins and installed external plugins. The newest package version is selected by default; installed packages win over built-in compatibility implementations when the `package_id` and version are the same.
  - The installed plugin view shows one active version per `package_id`. Installing another version switches the active version and removes unused older installs; versions pinned by existing Agents are retained for reproducibility but hidden from the installed plugin list.
- Built-in plugins:
  - `agent.loop.react`
  - `model.openai_compatible`
  - `model.openrouter`
  - `model.deepseek`
  - `memory.file`
  - `skill.registry`
  - `tool.runtime`
  - `tool.basic`
  - `context.compressor.summary`
  - `context.manager`
  - `mcp.bridge`
- Marketplace plugins include:
  - installable copies of the core built-in packages under `plugin-market/`
  - `context.compressor.model`
  - `workspace.sandbox`
  - `tool.greeter` sample package can be produced from `example-plugin/` for upload/install smoke checks.

## Public Plugin SDK

Plugin developers should depend on the public SDK surface, not private kernel implementation:

```python
from plugin_agent_sdk import Plugin


class WeatherPlugin(Plugin):
    def invoke(self, capability, payload, context):
        if capability == "tool.weather":
            return {"result": {"summary": "sunny"}}
        return super().invoke(capability, payload, context)
```

Plugins that support streaming may also implement `stream(capability, payload, context)` and yield event dictionaries matching the capability output schema. The kernel consumes the SDK protocol at runtime. A future private `plugin-agent-core` can remain closed while external plugins only install/import `plugin-agent-sdk`.

## Plugin Layout

Uploadable external plugins use this package layout:

```text
some_plugin/
  plugin.yaml
  config.yaml
  plugin.py
```

Current built-in compatibility implementations still live under `src/plugin_agent/plugins/`:

```text
some_plugin/
  manifest.yaml
  config.yaml
  plugin.py
  __init__.py
```

External/productized plugin packages must use `plugin.yaml`.

Manifest responsibilities:

- Package metadata.
- Provided capabilities.
- Required capabilities.
- Resource declarations.
- Config schema references and inline JSON schemas.
- Capability input/output schema references and inline JSON schemas.

## Plugin Package Format

External plugins can be uploaded as `.pluginpkg` files. A `.pluginpkg` is a zip archive with this minimum layout:

```text
plugin.yaml
plugin.py
```

Initial runtime support is intentionally small:

- `runtime.type` must be `python.in_process`.
- `runtime.entrypoint` must use `<file.py>:<PluginClass>`.
- The plugin class must extend `plugin_agent_sdk.Plugin`.
- Sibling Python modules inside the plugin package can be imported by the entrypoint module.

Marketplace packages must include `runtime.entrypoint`. Built-in compatibility plugins can still use `manifest.yaml`, but product plugins should be uploaded through the marketplace flow so they can evolve without changing the host.

For manual upload/install smoke checks, `../example-plugin/` contains a small `tool.greeter` package that exercises plugin upload, install, resource discovery, and tool invocation without importing private backend code.

## Code Sandbox Plugin

`../plugin-market/workspace_sandbox/` provides the `workspace.sandbox` marketplace package. It is a normal product plugin, not kernel code, and exposes coding tools through `tool.runtime`: `workspace.ls`, `workspace.read`, `workspace.write`, `workspace.edit`, `workspace.grep`, `workspace.glob`, and `workspace.bash`.

Each plugin instance must configure `workspace_root`. File tools enforce path, symlink, size, and protected-path guards inside that workspace. `workspace.edit` requires a prior `workspace.read` and rejects edits if the file changed after it was read.

`workspace.bash` applies command allow/deny policy and timeouts. On macOS, the default `sandbox.enabled: true` backend wraps commands with `/usr/bin/sandbox-exec`; on other platforms, OS command sandboxing is intentionally unavailable in v1 unless sandboxing is explicitly disabled and the caller accepts only path and command-policy guards.

Example `plugin.yaml`:

```yaml
id: tool.weather
version: 0.1.0
name: 天气工具
description: 返回指定城市的模拟天气。
runtime:
  type: python.in_process
  entrypoint: plugin.py:WeatherPlugin
provides:
  - name: tool.weather
    version: 1.0.0
resources:
  - kind: tool
    id: weather.lookup
    title: 天气查询
    invoke_capability: tool.weather
```

## Model Setup

Model providers are configured on their `PluginInstance` in the Agent Builder or workbench plugin configuration panel. Do not rely on environment variables for model API keys, model names, or base URLs.

Each model plugin declares a config schema in its manifest. Fields marked with `x-secret: true` or `x-encrypted: true` are stored as local secret refs and redacted in HTTP responses. The current development store protects secrets from ordinary config JSON exposure, but it is not a production-grade KMS/keyring-backed secret manager yet.

OpenAI-compatible model providers validate required config such as `api_key` during plugin startup. Missing config appears in Agent runtime diagnostics instead of waiting until the first chat run.

Example instance config:

```json
{
  "api_key": "sk-...",
  "base_url": "https://openrouter.ai/api/v1",
  "model": "openai/gpt-4o-mini",
  "timeout_seconds": 60
}
```

## Sessions and Memory

Chat sessions are product/runtime state, not plugin state. The host stores `sessions` and `session_messages` for each Agent and passes recent session messages to the selected Agent Loop as `context["history_messages"]`.

Memory plugins remain responsible for longer-lived or semantic memory capabilities such as `memory.query`, `memory.write`, and retrieval policies. Agent Loop plugins may combine both sources: deterministic session history from the host plus optional long-term memory from memory capabilities. The built-in file memory stores the current `agent_id` and `session_id` in automatic memory metadata and filters queries by that scope, so separate chat sessions do not leak remembered messages into each other.

Context rewriting is plugin-composed. Agent Loop plugins call `context.compress` when it is available. The built-in `context.manager` provides that capability, delegates summarization to a selected `context.compressor.compress` provider, and returns replacement messages for continued model reasoning. `context.compressor.summary` is a simple local transcript compactor, while `context.compressor.model` depends on `model.chat` and uses the selected model provider to generate a handoff summary.

## CLI

```bash
uv run plugin-agent plugins
uv run plugin-agent capabilities
uv run plugin-agent tools
uv run plugin-agent inspect-agent <agent-id>
uv run plugin-agent chat
```

Invoke a capability directly:

```bash
uv run plugin-agent invoke tool.invoke --payload '{"tool_id":"math.add","arguments":{"a":1,"b":2}}'
```

## Capability Discovery and Binding

`AgentKernel.discover_capability()` and `discover_capabilities()` expose the providers that can satisfy each capability, the selected provider, schema refs, and conflict status. Plugin code may still call known capabilities directly through `kernel.invoke(...)`; the kernel validates input/output schemas and raises structured `KernelInvokeError` details for missing capabilities, provider conflicts, unavailable providers, schema failures, and provider errors.

Saved Agents store provider choices in Agent-level `capability_bindings`, not plugin instance config. If multiple plugin instances provide the same capability, `/api/agents/{agent_id}/runtime` reports a `provider_conflict` diagnostic and the frontend asks the user to bind that capability to one provider instance.

## HTTP Service

```bash
uv run plugin-agent serve --host 127.0.0.1 --port 8000
```

Logging is configured by the CLI server entrypoint, not at import time. By default it writes INFO logs to stdout using:

```text
%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

Use `--log-level`, `PLUGIN_AGENT_LOG_LEVEL`, `--log-file`, or `PLUGIN_AGENT_LOG_FILE` to tune it:

```bash
uv run plugin-agent serve --log-level DEBUG --log-file .plugin-agent/logs/backend.log
```

Do not log secrets, full user messages, model responses, or workspace file contents. Prefer IDs, package names, status codes, diagnostic codes, and counts.

Core JSON endpoints:

```text
GET  /api/plugin-packages
GET  /api/installed-plugin-packages
POST /api/plugin-packages/refresh
GET  /api/plugins
GET  /api/marketplace/plugins
POST /api/marketplace/upload
POST /api/marketplace/install
DELETE /api/installed-plugin-packages/{package_id}
GET  /api/capabilities
GET  /api/tools
POST /api/agents/assemble
GET  /api/agents
POST /api/agents
GET  /api/agents/{agent_id}
PUT  /api/agents/{agent_id}
DELETE /api/agents/{agent_id}
GET  /api/agents/{agent_id}/sessions
POST /api/agents/{agent_id}/sessions
POST /api/agents/{agent_id}/run
POST /api/agents/{agent_id}/stream
POST /api/agents/stream
GET  /api/agents/{agent_id}/runtime
GET  /api/agents/{agent_id}/capabilities
GET  /api/agents/{agent_id}/capability-candidates
PUT  /api/agents/{agent_id}/capability-bindings
GET  /api/agents/{agent_id}/resources
GET  /api/sessions/{session_id}
GET  /api/sessions/{session_id}/messages
DELETE /api/sessions/{session_id}
PUT  /api/plugins/{plugin_id}/config
PUT  /api/plugin-instances/{instance_id}/config
POST /api/plugin-instances/{instance_id}/restart
POST /api/dev/validate-plugin
```

Streaming endpoints return `text/event-stream`. Each event has `event: <type>` and `data: <StreamEvent JSON>` where the JSON contains `type`, `sequence`, `run_id`, and `payload`.

## Tests

```bash
uv run pytest -q
```
