# 开发新插件

插件是 Agent 能力的唯一扩展单元。第三方插件应该只依赖公共 SDK `plugin_agent_sdk`，通过 capability 与其他插件协作，不直接导入后端私有内核代码。可以从 [example-plugin](../example-plugin) 复制一个最小工具插件开始，参考 [plugin-market/http-tool-plugin](../plugin-market/http-tool-plugin) 了解带配置、密钥 header 和外部请求的工具插件，也可以参考面向 Agent 的插件开发 Skill：[develop-plugin-agent-plugins](../.agents/skills/develop-plugin-agent-plugins/SKILL.md)。

## 1. 准备插件包

插件开发者只需要准备一个本地插件包目录，目录名可以任意，最小结构如下：

```text
your-plugin/
  plugin.yaml
  config.yaml       # 可选：默认配置
  plugin.py
```

`example-plugin/` 是一个最小工具插件示例。`plugin-market/http-tool-plugin/` 是一个更完整的 HTTP 集成工具示例，包含固定端点、可选 Raw 请求、普通 header、敏感 header、host allowlist 和响应解析。开发新插件时，可以复制最接近的示例到任意工作目录后改名。

复杂插件可以继续在目录内增加 Python 模块或子包，让 `plugin.py` 只保留入口类和 capability 路由，例如 `workspace.sandbox` 把文件读写、搜索和命令执行拆在 `workspace_tools/` 下。

```bash
cp -R example-plugin ~/my-plugin
```

不要手动修改后端运行时目录或仓库内的插件市场目录；插件进入系统应通过前端“上传插件包”按钮完成。

## 2. 声明插件契约

`plugin.yaml` 是插件的公开契约，至少要声明：

- `descriptor.id` / `version` / `name` / `description`：包身份和展示信息。
- `runtime.type: python.in_process` 和 `runtime.entrypoint: plugin.py:<PluginClass>`：运行时入口。
- `provides`：插件提供的 capability 名称、版本、输入/输出 schema 引用。
- `requires`：插件依赖的其他 capability，标明 `required: true/false`。
- `resources`：给 UI 和 Agent Loop 发现的语义资源，例如 `kind: tool`。
- `schemas`：所有输入、输出、配置 schema。除非刻意开放，建议 `additionalProperties: false`。

能力命名使用点分命名空间，例如 `tool.weather_current`、`memory.read`、`context.compress`。schema ref 使用稳定 URI，例如 `schema://tool.weather_current.input.v1`。

## 3. 实现运行时代码

插件类继承 `plugin_agent_sdk.Plugin`：

```python
from __future__ import annotations

from typing import Any

from plugin_agent_sdk import Plugin


class MyToolPlugin(Plugin):
    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability == "tool.my_action":
            return {"result": {"ok": True}}
        return super().invoke(capability, payload, context)
```

实现规范：

- 不导入 `plugin_agent.*` 私有模块；公共类型和基类来自 `plugin_agent_sdk`。
- 不直接实例化或调用其他插件；需要协作时使用 `self.kernel.invoke(...)` 或 `self.kernel.stream(...)`。
- 可选依赖调用失败时要降级；必需依赖写进 `descriptor.requires`，由内核在启动时阻断。
- 多个插件提供同一 capability 时不要在插件代码里选择 provider；让 Agent 的 `capability_bindings` 决定。
- 密钥字段必须在 config schema 中标记 `x-secret: true` 或 `x-encrypted: true`。
- 支持流式输出时实现 `stream(...)`，并让每个事件符合 capability 的输出 schema。

## 4. 验证和安装

开发阶段可以先运行后端测试确认 SDK 和插件市场链路没有被破坏：

```bash
cd backend
uv run pytest tests/test_plugin_market.py -q
uv run pytest -q
```

本地调试时启动控制台，进入“插件市场”，点击“上传插件包”，选择插件目录或打包后的 `.pluginpkg`。上传完成后在插件市场安装插件，再到 Agent 工作台中为 Agent 添加并配置插件实例。如果只想验证上传链路，可以直接上传 `example-plugin/`；HTTP 请求工具已经作为本地市场包提供，可直接在插件市场安装后配置 `endpoints`、`security.allowed_hosts` 和 `secret_headers`。
