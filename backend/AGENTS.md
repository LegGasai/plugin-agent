# Backend AGENTS.md

Guidance for agents working in `backend/`.

## Scope

This subrepo contains the Python backend:

- Private kernel and runtime in `src/plugin_agent/`.
- Product orchestration services in `src/plugin_agent/services/`; `src/plugin_agent/assembly.py` is a compatibility facade that re-exports the service entrypoints.
- SQLite and secret persistence in `src/plugin_agent/stores/`.
- Internal typed records in `src/plugin_agent/models/`.
- Pure config, version, and time helpers in `src/plugin_agent/utils/`.
- Public plugin SDK in `src/plugin_agent_sdk/`.
- Local marketplace plugin packages in `../plugin-market/`.
- Compatibility implementations and direct provider test fixtures in `src/plugin_agent/plugins/`.
- External installed plugins in `.plugin-agent/installed-plugins/` at runtime.
- Sample external upload fixture in `../example-plugin/`.
- HTTP tool marketplace package in `../plugin-market/http-tool-plugin/`.
- Workspace sandbox coding package in `../plugin-market/workspace_sandbox/`.
- Tests in `tests/`.

## Kernel and SDK Boundary

External plugins must import from `plugin_agent_sdk`, not private kernel modules.

Preferred:

```python
from plugin_agent_sdk import Plugin
```

Avoid in new third-party plugin code:

```python
from plugin_agent.kernel import PluginBase
from plugin_agent.contracts import SchemaDefinition
```

Compatibility shims may remain, but new public contracts belong in `plugin_agent_sdk`.

## Plugin Marketplace and Installation

Keep these locations distinct:

- `plugin-market/`: local development stand-in for a remote marketplace and internal storage behind the frontend upload/install flow.
- `src/plugin_agent/plugins/`: compatibility/runtime implementations retained for host tests and legacy helpers, not the product package registry.
- `.plugin-agent/installed-plugins/`: runtime installation directory for unpacked external plugins, stored by `package_id/version`.

Do not place new plugin source directly under `.plugin-agent/installed-plugins/`; install it through the marketplace upload/install flow so marketplace and installed state stay synchronized.
On backend startup, `AgentAssemblyService` ensures the default package set in `DEFAULT_PLUGIN_INSTALLS` is installed from `plugin-market/` when those marketplace packages are present. Missing default packages are diagnostics, not a reason to register source-tree built-ins.

Keep the HTTP views distinct as well:

- `GET /api/marketplace/plugins` returns packages from the marketplace source.
- `GET /api/installed-plugin-packages` returns installed packages available for Agent assembly.
- `DELETE /api/installed-plugin-packages/{package_id}` uninstalls installed packages when they are not used by saved plugin instances.
- `GET /api/plugin-packages` is a compatibility alias for the installed-package view.

External plugin packages use `.pluginpkg` zip files with a required `plugin.yaml`. Initial runtime support is `python.in_process` with an entrypoint like `plugin.py:WeatherPlugin`. External plugin classes must import and extend `plugin_agent_sdk.Plugin`. Entry modules may import sibling Python modules from the same plugin package.

Default package selection chooses the newest installed version for a `package_id`. The installed-package view exposes one active version per `package_id`. Older installed versions may remain only when saved Agent plugin instances still pin that `package_version`; do not surface those retained versions as separately installed plugins. `plugin-market/` is the product source of truth for plugin evolution, and runtime copies live under `.plugin-agent/installed-plugins/`.

Use `../example-plugin/` for local upload/install smoke checks when a full plugin package fixture is not needed. Use `../plugin-market/http-tool-plugin/` when testing configured tool integrations, dynamic secret header config, or endpoint/raw HTTP request behavior.

## Plugin Communication

Plugins communicate through capability routing:

```python
self.kernel.invoke("memory.read", {"path": "MEMORY.md"}, context)
self.kernel.stream("agent.stream", {"message": text}, context)
```

Do not make plugins import or call each other directly.

Plugins may inspect known capability contracts through kernel discovery helpers such as `discover_capability(...)`, `discover_capabilities()`, and `get_schema(...)`. Keep this as discovery of runtime contracts, not a reason to import private provider implementations.

The kernel owns:

- Provider lookup.
- Capability discovery and candidate reporting.
- Explicit `Capability -> PluginInstance` binding when multiple providers are installed for the same Agent.
- Input schema validation.
- Provider invocation.
- Streaming provider invocation for capabilities whose plugin implements `stream(...)`.
- Output schema validation.
- Lifecycle state.

When multiple plugin instances provide the same capability in one Agent, do not pick a provider implicitly. Require an Agent-level `capability_bindings` entry such as `{"model.chat": "pi-..."}` and return runtime diagnostics for missing bindings, missing dependencies, or version mismatches. Binding data belongs to the Agent assembly, not to any plugin instance's business config.

When adding plugin-to-plugin calls, handle `KernelInvokeError`-style structured failures where appropriate. Required dependencies should be blocked during startup; optional dependencies should degrade gracefully if invoke fails.

Context rewriting must remain plugin-composed. Agent Loop plugins should call `context.compress` when available; `context.manager` owns message replacement and delegates summarization to a selected `context.compressor.compress` provider. Compressor plugins must not also provide `context.compress` unless they intentionally replace the context manager in an Agent with explicit capability bindings.

## Product Model

Preserve these distinctions:

- `PluginPackage`: static plugin package metadata.
- `PluginInstance`: per-Agent instance with package version, config, secret refs, state, and generation.
- `Agent`: assembly of plugin instances with one Agent Loop entry.
- `Session`: host-owned chat thread for one Agent, persisted separately from plugin memory.
- `Capability`: machine-callable API contract.
- `Resource`: discoverable semantic object for UI and Agent Loop discovery.

Do not collapse plugin instances back into global plugin IDs.
Do not add plugin enable/disable semantics for this phase. A plugin participates in an Agent only when that Agent has a plugin instance for it.

Sessions are product/runtime state, not plugin-owned state. The host stores session messages and passes them to Agent Loop plugins through `context["history_messages"]`; memory plugins still own longer-lived memory through memory capabilities. Markdown memory providers should expose `memory.read` and `memory.write` tools, keep `MEMORY.md` as an index, and let Agent Loop plugins inject only the index unless the model explicitly reads a memory file.

## Backend Layering

Keep backend product code layered:

- `services/`: product workflows such as Agent assembly, marketplace install/uninstall, runtime inspection, plugin instance config, and session run/stream orchestration.
- `stores/`: persistence boundaries only. Stores should not build kernels, know HTTP routes, or call plugin capabilities.
- `models/`: internal typed records and DTO-style shapes. Prefer `TypedDict` or dataclasses for stable database and service records instead of unbounded `dict[str, Any]`.
- `utils/`: pure helper functions with no store/service/kernel state.

Use `plugin_agent.assembly` as a stable compatibility import for existing callers, but put new implementation code in the layered modules above. Keep dynamic plugin payloads, JSON Schemas, and arbitrary plugin config as `dict[str, Any]`; add typed outer records around stable product objects such as Agent, PluginInstance, Session, and SessionMessage.

## Adding Plugins

For new product plugins, prepare an uploadable package directory with `plugin.yaml`, optional `config.yaml`, and an entrypoint such as `plugin.py`, then install it through the frontend marketplace upload flow. Include `runtime.type: python.in_process` and `runtime.entrypoint: plugin.py:<PluginClass>`. Larger plugins may include sibling modules or internal packages; keep `plugin.py` as a thin entrypoint when the implementation grows.

Marketplace plugin runtime code must depend on `plugin_agent_sdk` and standard/library dependencies only; do not import from private `plugin_agent.*` modules. If a marketplace plugin needs shared logic, duplicate the small adapter locally for now or move the shared surface into the public SDK.

Add product plugins under `plugin-market/` as uploadable packages, then install them through the normal upload/install flow. Add code under `src/plugin_agent/plugins/` only for compatibility/runtime helpers that must be imported by backend tests or legacy code; do not register those helpers as product packages from `assembly.py`.

Model providers must normalize provider-specific responses into the standard `model.chat` output and, when streaming, `model.chat.stream` events. Validate required provider config such as `api_key` during `start()` so `/api/agents/{agent_id}/runtime` reports missing config. ReAct Agent Loop must not parse provider-specific raw responses.

Agent Loop plugins should enforce their own operation timeouts for tool calls. MCP bridge plugins must apply configured request timeouts to subprocess protocol reads and close subprocesses on startup failure.

Skill-aware Agent Loop plugins should inject only a compact Skill catalog into system context, normally the Skill name and description from `skill.list`. When the model needs more detail, route through tool resources backed by `skill.activate` and `skill.read_file`; do not eagerly inject full `SKILL.md` contents.

Code sandbox and coding capabilities should remain ordinary marketplace plugins. `workspace.sandbox` is the current reference package: it exposes file and command tools through `tool.runtime`, requires an explicit `workspace_root`, keeps file operations inside that root, and wraps macOS command execution with Seatbelt when sandboxing is enabled. Do not move this behavior into the kernel or broaden workspace access without schema changes and tests for path escape, protected paths, command policy, timeouts, and sandbox behavior.

Local CLI Agent Loop bridges such as `agent.loop.codex_bridge` and `agent.loop.claude_code_bridge` should stay product plugins under `plugin-market/`. They may invoke local CLIs, but must require an explicit `workspace_root`, apply timeouts, stream only events matching `agent.stream.event.v1`, and make dangerous permission-bypass flags opt-in config fields.

## Secrets

Plugin config secrecy is declared by the plugin config JSON Schema, not guessed from field names.

Use `x-secret: true` or `x-encrypted: true` on config schema properties that must be treated as secret values. HTTP responses must redact those fields, and backend config updates must treat the redaction sentinel `"********"` as “keep the existing value”. The current development store keeps local secret refs out of ordinary config JSON, but it is not a production-grade KMS/keyring-backed secret manager yet.

Do not add model-provider environment variables as the product configuration path. Model API keys, model names, base URLs, and similar fields belong to `PluginInstance.config`.

## Logging

Use `plugin_agent.logging_config.configure_logging()` only from process entrypoints such as the CLI server or a future local desktop app host. Do not call `logging.basicConfig()` from importable modules.

Backend logs should be useful for local diagnosis without leaking data. Log lifecycle events, package IDs, plugin instance IDs, agent/session IDs, runtime status, diagnostic codes, request paths, and exception traces. Do not log secrets, redacted secret placeholders, full chat messages, model outputs, uploaded package contents, or workspace file contents.

## Verification

Run from `backend/`:

```bash
uv run pytest -q
```

Focused tests:

```bash
uv run pytest tests/test_sdk.py -q
uv run pytest tests/test_real_plugins.py -q
uv run pytest tests/test_product_model.py -q
uv run pytest tests/test_plugin_market.py -q
uv run pytest tests/test_http_service.py -q
```

## Local Run

```bash
uv run plugin-agent serve --host 127.0.0.1 --port 8000
```

If debugging stale API behavior, check for an old backend process:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```
