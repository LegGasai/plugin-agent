# Plugin Patterns

Use this reference for implementation templates after the capability contract is chosen.

## Minimal Plugin Runtime

```python
from __future__ import annotations

from typing import Any

from plugin_agent_sdk import Plugin as PluginBase


class ExamplePlugin(PluginBase):
    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability == "tool.example_run":
            return {"result": payload["text"]}
        return super().invoke(capability, payload, context)
```

Keep unknown-capability handling delegated to `super().invoke(...)`; it produces a clear not-handled error.

## Tool Plugin

Use when the Agent loop should discover callable functions through `tool.runtime`.

Checklist:

- `descriptor.categories: [tool]`
- one `provides` entry per tool capability
- one `resources` entry per callable tool with `kind: tool`
- input/output schemas with `additionalProperties: false`
- tests invoke through both direct capability and `tool.invoke` when tool runtime is in scope

Representative package: `plugin-market/tool_basic/` with compatibility implementation in `backend/src/plugin_agent/plugins/tool_basic/`.

## Model Provider

Use when providing normalized `model.chat`.

Checklist:

- provide `model.chat` with the shared schema refs currently used by model marketplace packages
- keep provider-specific API responses out of Agent loop code
- normalize output to `{"message": {"role": "assistant", "content": str, "tool_calls": [...]}, "raw": ...}`
- parse tool call arguments into dicts; preserve unparseable strings under a safe key such as `"_raw"`
- place API keys and model selection in `PluginInstance.config`, not environment variables

For OpenAI-compatible providers, subclass or mirror `OpenAIChatModelPluginBase` from `model_openai_compatible/plugin.py` when that keeps behavior identical.

Representative packages: `model_openai_compatible`, `model_openrouter`, `model_deepseek`.

## Memory Provider

Use when storing or retrieving semantic Agent memory.

Checklist:

- provide `memory.write`, `memory.query`, or both
- keep durable paths configurable through `config.yaml` and config schema
- create needed runtime directories in `start()`
- return stable item objects and include caller metadata when useful
- avoid global state shared across plugin instances

Representative package: `memory_file`.

## Agent Loop

Use when implementing the runtime entry point for an Agent.

Checklist:

- provide `agent.run`
- add an `agent_loop` resource so product assembly can select it as the entry loop
- declare required dependencies such as `model.chat`, `memory.query`, `memory.write`, `tool.registry.list`, and `tool.invoke`
- call dependencies through `self.kernel.invoke(...)`
- return transcript/events/audit structures that make failures diagnosable
- do not parse provider-specific raw model responses

Representative package: `agent_loop_react`.

## Bridge or Dynamic Tool Provider

Use when adapting an external protocol or subprocess to plugin capabilities.

Checklist:

- perform external discovery in `start()` when schemas or tool definitions must be registered dynamically
- register dynamic schemas through `kernel.schema_registry.register(...)`
- expose discovered callables through `self.tool_definitions` or `kind: tool` resources
- clean up subprocesses, sockets, or clients in `stop()`
- make ambiguity explicit in payload or config instead of guessing

Representative package: `mcp_bridge_plugin`.

## Test Skeleton

```python
from plugin_agent.kernel import AgentKernel
from plugin_agent.plugins.tool_runtime_plugin.plugin import ToolRuntimePlugin
from plugin_agent.plugins.<plugin_folder>.plugin import ExamplePlugin


def test_example_tool_invokes_through_tool_runtime():
    kernel = AgentKernel()
    kernel.load_plugins([ToolRuntimePlugin(), ExamplePlugin()])
    kernel.start_all()

    result = kernel.invoke("tool.invoke", {"tool_id": "example.run", "arguments": {"text": "hi"}}).payload

    assert result["result"] == "hi"
```

Add direct capability tests when schema validation, config behavior, dependency diagnostics, or provider-specific normalization matter.
