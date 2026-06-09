# Backend AGENTS.md

Guidance for agents working in `backend/`.

## Scope

This subrepo contains the Python backend:

- Private kernel and runtime in `src/plugin_agent/`.
- Public plugin SDK in `src/plugin_agent_sdk/`.
- Local marketplace plugin packages in `../plugin-market/`.
- Built-in compatibility implementations in `src/plugin_agent/plugins/`.
- External installed plugins in `.plugin-agent/installed-plugins/` at runtime.
- Sample external upload fixture in `../test-plugin/`.
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

- `plugin-market/`: local development stand-in for a remote marketplace; new user-facing/product plugins live here as unpacked directories, and uploaded `.pluginpkg` artifacts are stored there and ignored by git.
- `src/plugin_agent/plugins/`: compatibility/built-in runtime implementations used while the platform is transitioning fully to installed plugin loading.
- `.plugin-agent/installed-plugins/`: runtime installation directory for unpacked external plugins, stored by `package_id/version`.

Do not place new plugin source directly under `.plugin-agent/installed-plugins/`; install it from `plugin-market/` so marketplace and installed state stay synchronized.

Keep the HTTP views distinct as well:

- `GET /api/marketplace/plugins` returns packages from the marketplace source.
- `GET /api/installed-plugin-packages` returns built-in and installed packages available for Agent assembly.
- `DELETE /api/installed-plugin-packages/{package_id}` uninstalls external installed packages only; built-in packages are not deleted.
- `GET /api/plugin-packages` is a compatibility alias for the installed-package view.

External plugin packages use `.pluginpkg` zip files with a required `plugin.yaml`. Initial runtime support is `python.in_process` with an entrypoint like `plugin.py:WeatherPlugin`. External plugin classes must import and extend `plugin_agent_sdk.Plugin`. Entry modules may import sibling Python modules from the same plugin package.

Installed external packages take precedence over built-in compatibility implementations when they share the same `package_id`. Multiple installed versions can coexist, and saved Agent plugin instances must pin `package_version` so later installs do not silently change runtime behavior. This is intentional: `plugin-market/` is the product source of truth for plugin evolution, and `src/plugin_agent/plugins/` is the host fallback while the platform transitions.

Use `../test-plugin/` for local upload/install smoke checks when a full marketplace package is not needed.

## Plugin Communication

Plugins communicate through capability routing:

```python
self.kernel.invoke("memory.query", {"query": text, "limit": 5}, context)
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

Sessions are product/runtime state, not plugin-owned state. The host stores session messages and passes them to Agent Loop plugins through `context["history_messages"]`; memory plugins still own long-term or semantic memory through memory capabilities. When automatically writing chat turns into memory, include `agent_id` and `session_id` from context and query by the same scope unless a plugin explicitly implements cross-session memory policy.

## Adding Plugins

For new product plugins, add an unpacked package under `../plugin-market/` with `plugin.yaml`, `config.yaml`, and `plugin.py`. Include `runtime.type: python.in_process` and `runtime.entrypoint: plugin.py:<PluginClass>`.

Marketplace plugin runtime code must depend on `plugin_agent_sdk` and standard/library dependencies only; do not import from private `plugin_agent.*` modules. If a marketplace plugin needs shared logic, duplicate the small adapter locally for now or move the shared surface into the public SDK.

Add a built-in plugin under `src/plugin_agent/plugins/` only when it is a compatibility/runtime implementation that must ship as part of the backend host. Built-ins must still use `plugin_agent_sdk.Plugin`, register a factory in `src/plugin_agent/assembly.py`, and include tests for provider behavior and package discovery.

Model providers must normalize provider-specific responses into the standard `model.chat` output and, when streaming, `model.chat.stream` events. Validate required provider config such as `api_key` during `start()` so `/api/agents/{agent_id}/runtime` reports missing config. ReAct Agent Loop must not parse provider-specific raw responses.

Agent Loop plugins should enforce their own operation timeouts for tool calls. MCP bridge plugins must apply configured request timeouts to subprocess protocol reads and close subprocesses on startup failure.

## Secrets

Plugin config secrecy is declared by the plugin config JSON Schema, not guessed from field names.

Use `x-secret: true` or `x-encrypted: true` on config schema properties that must be treated as secret values. HTTP responses must redact those fields, and backend config updates must treat the redaction sentinel `"********"` as “keep the existing value”. The current development store keeps local secret refs out of ordinary config JSON, but it is not a production-grade KMS/keyring-backed secret manager yet.

Do not add model-provider environment variables as the product configuration path. Model API keys, model names, base URLs, and similar fields belong to `PluginInstance.config`.

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
