# Plugin Mechanism

Use this reference when designing plugin contracts, manifests, lifecycle behavior, default marketplace installation, or tests.

## Source Map

- Public SDK: `backend/src/plugin_agent_sdk/`
- Private kernel: `backend/src/plugin_agent/kernel.py`
- Marketplace plugins: `plugin-market/`
- Compatibility implementations and provider test fixtures: `backend/src/plugin_agent/plugins/`
- Default marketplace installation and product model: `backend/src/plugin_agent/assembly.py`
- Tests: `backend/tests/test_sdk.py`, `test_builtin_plugins.py`, `test_real_plugins.py`, `test_kernel.py`, `test_product_model.py`

## Uploadable Plugin Layout

Use this for new product plugins before uploading through the frontend marketplace flow:

```text
<plugin_folder>/
├── config.yaml
├── plugin.yaml
└── plugin.py
```

`plugin.yaml` must include `runtime.type: python.in_process` and `runtime.entrypoint: plugin.py:<PluginClass>` so upload/install validation can load it. Do not write plugin source directly into `.plugin-agent/installed-plugins/`; use the marketplace upload/install flow instead. `plugin-market/` is the local development storage behind that flow, not a user-facing destination.

## Compatibility Plugin Layout

Use this only for compatibility/runtime helpers that must ship as part of the backend host or be imported by direct provider tests:

```text
backend/src/plugin_agent/plugins/<plugin_folder>/
├── __init__.py
├── config.yaml
├── manifest.yaml
└── plugin.py
```

`plugin_agent_sdk.Plugin` discovers its own directory from the subclass file, then reads `plugin.yaml` if present, otherwise `manifest.yaml`. Marketplace/product plugins use `plugin.yaml`; compatibility helpers may still use `manifest.yaml`.

`config.yaml` contains default instance config. Constructor overrides are shallow-merged over file config.

## Manifest Shape

Prefer the current descriptor style:

```yaml
descriptor:
  id: tool.example
  version: 1.0.0
  name: Example Tool
  description: Provides an example tool.
  categories: [tool]
  config_schema_ref: schema://tool.example.config.v1
  requires: []
  provides:
    - name: tool.example_run
      version: 1.0.0
      input_schema_ref: schema://tool.example_run.input.v1
      output_schema_ref: schema://tool.example_run.output.v1
runtime:
  type: python.in_process
  entrypoint: plugin.py:ExamplePlugin
resources:
  - kind: tool
    id: example.run
    title: Example Run
    description: Run the example operation.
    invoke_capability: tool.example_run
    schema_refs:
      input: schema://tool.example_run.input.v1
      output: schema://tool.example_run.output.v1
schemas:
  - schema_ref: schema://tool.example.config.v1
    json_schema:
      type: object
      additionalProperties: false
      properties: {}
```

For user-callable tools, either declare `resources` with `kind: tool` or add `tool_definitions`. `tool.runtime` collects tool resources from the resource registry and also reads each plugin's `tool_definitions`.

## Lifecycle

`Plugin` methods:

- `__init__(config=None, instance_id=None)`: loads manifest/config and validates descriptor/resource models.
- `start(kernel)`: save kernel reference and perform setup.
- `after_start_all(kernel)`: refresh state that depends on all active plugins.
- `invoke(capability, payload, context)`: return a dict matching the output schema.
- `stop()`: release resources.

Kernel startup:

1. `load_plugin()` registers schemas and stores plugin instances.
2. `start_all()` collects capability candidates.
3. It selects providers. One provider is selected automatically; multiple providers require `capability_bindings`.
4. It starts plugins only after required dependencies are active.
5. It registers selected provided capabilities and all resources.
6. It calls `after_start_all()` on active plugins.

Input and output schemas are validated at `kernel.invoke(...)`.

`AgentKernel.discover_capability(name)` and `discover_capabilities()` expose selected providers, provider candidates, plugin instance ids, and schema refs for runtime inspection. Use `get_schema(schema_ref)` to retrieve a registered JSON Schema. These helpers are for contract discovery; plugins still call other plugins only through capabilities.

`kernel.invoke(...)` raises structured kernel errors for missing capabilities, unresolved provider conflicts, unavailable providers, schema validation failures, and provider exceptions. Required dependencies should be represented in `descriptor.requires`; optional dependencies should catch invoke failures and degrade.

## Dependencies and Provider Binding

Declare dependencies in `descriptor.requires`:

```yaml
requires:
  - capability: model.chat
    version: ">=1.0 <2.0"
    required: true
```

When multiple plugin instances provide the same capability, the Agent must carry a binding such as:

```json
{"model.chat": "pi-model-openrouter"}
```

Do not resolve provider conflicts inside plugin code. Agent-level `capability_bindings` are runtime assembly metadata and must not be stored inside an individual plugin instance's business config. The workbench can read runtime diagnostics and capability candidates, ask the user to select a provider, and write the binding back to the Agent.

## Secrets

Declare secret config fields in the config JSON Schema:

```yaml
api_key:
  type: [string, "null"]
  title: API Key
  x-secret: true
  x-encrypted: true
```

The assembly service collects encrypted paths from the schema, stores secret refs, hydrates config before instantiation, and redacts secrets in API responses.

## Built-in Registration

For a new marketplace plugin:

1. Prepare an uploadable plugin folder or `.pluginpkg` artifact.
2. Implement runtime code using `plugin_agent_sdk.Plugin`.
3. Add `plugin.yaml`, `config.yaml`, schemas, resources, and runtime entrypoint.
4. Upload/install through the marketplace flow or API in tests.
5. Add marketplace tests that confirm it appears in `GET /api/marketplace/plugins` and not in `GET /api/installed-plugin-packages` until installed.

For a default product plugin:

1. Add or update the uploadable package under `plugin-market/`.
2. Add the package ID to `DEFAULT_PLUGIN_INSTALLS` only if the backend should auto-install the latest marketplace version on startup when no version is installed yet.
3. Add it to `DEFAULT_AGENT_PLUGIN_IDS` only if every default Agent should include it.
4. If legacy `build_default_kernel()` should include it for direct tests, update `backend/src/plugin_agent/kernel.py`.
5. Update frontend plugin metadata only when UI labels or selection behavior depend on it.

## Test Anchors

Use these existing tests as patterns:

- `test_sdk.py`: public SDK plugin can be loaded by private kernel.
- `test_builtin_plugins.py`: built-ins load from folders with manifests.
- `test_real_plugins.py`: real provider behavior and integration flows.
- `test_kernel.py`: dependency diagnostics, provider conflicts, version matching.
- `test_product_model.py`: plugin package discovery, instances, config, secrets, and capability bindings.

Prefer focused tests during development, then run `cd backend && uv run pytest -q`.
