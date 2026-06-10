---
name: develop-plugin-agent-plugins
description: Develop backend plugins for the plugin-agent monorepo. Use when Codex needs to design, create, modify, or test plugin-agent plugins, plugin manifests, config schemas, capabilities, resources, tool/model/memory/agent-loop/MCP plugins, built-in plugin registration, or plugin SDK usage.
---

# Develop Plugin Agent Plugins

## Overview

Build plugin-agent plugins as microkernel extensions. Keep the backend kernel private and expose plugin behavior through SDK contracts, capabilities, resources, schemas, and per-Agent plugin instances.

## Start Here

1. Read `/Users/leggasai/projects/pyProjects/plugin-agent/AGENTS.md` and `backend/AGENTS.md` before changing backend code.
2. Inspect the closest built-in plugin under `backend/src/plugin_agent/plugins/`.
3. Read `references/plugin-mechanism.md` when designing metadata, lifecycle, capability dependencies, registration, or tests.
4. Read `references/plugin-patterns.md` when implementing a tool, model provider, memory provider, Agent loop, MCP bridge, or other common plugin shape.

## Design Rules

- Import public plugin contracts from `plugin_agent_sdk`; do not make third-party plugin code import private kernel modules.
- Treat capabilities as the only plugin-to-plugin API. Use `self.kernel.invoke("<capability>", payload, context)` instead of importing another plugin.
- Use kernel discovery helpers when a plugin needs to inspect installed providers or schema refs for a known capability.
- Keep `PluginPackage`, `PluginInstance`, `Agent`, `Capability`, and `Resource` distinct.
- Define every capability with input and output JSON Schemas unless the payload is intentionally unconstrained.
- Declare secrets in the config schema with `x-secret: true` or `x-encrypted: true`; do not infer secrecy from field names.
- If multiple providers can satisfy the same capability, require Agent-level `capability_bindings` instead of choosing implicitly.
- Binding data belongs to the Agent assembly, not to plugin instance config.
- Build new product plugins as uploadable package directories with `plugin.yaml`, optional `config.yaml`, and `plugin.py`; do not write plugin source directly into `.plugin-agent/installed-plugins/`.
- Use built-in plugin layout under `backend/src/plugin_agent/plugins/` only for host compatibility/runtime plugins that must ship with the backend.

## Development Workflow

1. Classify the plugin:
   - `tool`: user-callable function exposed through `tool.runtime`.
   - `model`: provider for normalized `model.chat`.
   - `memory`: provider for `memory.write` and/or `memory.query`.
   - `agent_loop`: entry resource that provides `agent.run`.
   - `bridge`: adapter that discovers or routes external capabilities.
2. Design the public contract first:
   - capability names use dotted namespaces such as `tool.weather_current`.
   - schema refs use stable URIs such as `schema://tool.weather_current.input.v1`.
   - resources describe discoverable semantic objects for the UI and Agent loop.
3. Implement runtime code:
   - subclass `plugin_agent_sdk.Plugin`.
   - override `start()` only for setup that needs the kernel or filesystem.
   - override `after_start_all()` only when discovery depends on all active plugins.
   - implement `invoke()` with explicit capability branches and delegate unknown capabilities to `super().invoke(...)`.
4. Package and register the plugin:
   - for a new product plugin, prepare an uploadable package directory and include `runtime.type: python.in_process` plus `runtime.entrypoint: plugin.py:<PluginClass>` in `plugin.yaml`.
   - install product plugins through the frontend marketplace upload flow; treat `plugin-market/` as internal storage rather than user-facing instructions.
   - for a true built-in, add imports and entries to `PLUGIN_FACTORIES` in `backend/src/plugin_agent/assembly.py`.
   - add a built-in to `DEFAULT_AGENT_PLUGIN_IDS` only when it should participate in new default Agents.
   - update `frontend/src/lib/plugins.js` only if frontend labels or selection behavior need to change.
5. Test the smallest useful surface:
   - package discovery and manifest/config loading.
   - direct capability invocation through `AgentKernel`.
   - dependency diagnostics when required providers are missing or ambiguous.
   - HTTP/product-model behavior when plugin instances, config schemas, or secrets are affected.

## Verification

Run focused backend tests while iterating, then run the full backend suite before finishing:

```bash
cd /Users/leggasai/projects/pyProjects/plugin-agent/backend
uv run pytest tests/test_sdk.py tests/test_real_plugins.py tests/test_builtin_plugins.py -q
uv run pytest -q
```

If frontend plugin catalog behavior changes, also run:

```bash
cd /Users/leggasai/projects/pyProjects/plugin-agent/frontend
yarn build
```

If project docs or agent instructions change, use `$maintain-project-docs`.

## References

- `references/plugin-mechanism.md`: current microkernel, SDK, manifest, lifecycle, secrets, registration, and test mechanics.
- `references/plugin-patterns.md`: concise templates for common plugin categories.
