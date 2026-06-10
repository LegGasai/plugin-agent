# Plugin Agent

<p align="center">
  <strong>一个轻量、可插拔、面向产品化实验的 Agent 平台</strong>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-Console-61DAFB?logo=react&logoColor=111111">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white">
  <img alt="Plugins" src="https://img.shields.io/badge/Pluginized-Agent-7C3AED">
</p>

Plugin Agent 把 Agent 系统拆成一个稳定内核和一组可安装插件：模型、工具、记忆、技能、MCP 桥接、上下文压缩和 Agent Loop 都可以独立演进。你可以像组装产品一样创建 Agent、配置插件实例、绑定能力提供方，并在控制台里直接运行带会话历史的流式对话。

这个项目适合用来验证插件化 Agent 架构、构建内部工具型 Agent、试验模型/工具/记忆组合，以及开发可分发的本地插件包。

## 核心能力

- 插件市场：通过控制台上传、安装、卸载和版本化管理插件包。
- Agent 装配：每个 Agent 都由独立插件实例组成，配置、密钥引用、生命周期和版本互不干扰。
- 能力路由：插件通过 `Capability` 调用彼此，内核负责 provider 选择、schema 校验、错误诊断和流式调用。
- 可视化控制台：React 控制台提供插件市场、Agent 广场、工作台、插件配置、会话列表和流式聊天。
- 运行时诊断：当模型配置缺失、依赖能力缺失或多个 provider 冲突时，后端会给出 Agent 运行时报告。
- 会话与记忆：会话历史由主机持久化，长期记忆由插件提供，Agent Loop 可以同时使用两者。
- 代码沙盒：`workspace.sandbox` 插件在隔离目录内提供 `ls/read/write/edit/grep/glob/bash` coding 工具，macOS 下命令执行可使用 Seatbelt 沙箱。
- Docker 部署：提供 backend + frontend 的 Docker Compose，一条命令即可启动完整控制台。

## 快速开始

### Docker 一键启动

```bash
cd docker
cp .env.example .env
docker compose up --build
```

打开控制台：

```text
http://127.0.0.1:8080
```

Docker 会加载内置插件包，并把运行时数据持久化到 `docker/volumes/plugin-agent-data`。

### 本地开发启动

后端：

```bash
cd backend
uv run plugin-agent serve --host 127.0.0.1 --port 8000
```

日志默认输出到 stdout，格式为 `时间 - logger - 级别 - 消息`。开发时可调整级别；如果未来打成本地 App，可以把日志写入用户数据目录方便排障：

```bash
uv run plugin-agent serve --log-level DEBUG --log-file ~/.plugin-agent/logs/backend.log
```

前端：

```bash
cd frontend
yarn install
yarn dev --host 127.0.0.1 --port 5173
```

打开：

```text
http://127.0.0.1:5173
```

## 项目结构

```text
plugin-agent/
  backend/          Python Agent 内核、HTTP API、SDK、内置插件和测试
  frontend/         React 控制台
  docker/           Docker Compose 部署配置
  docs/             用户文档
  example-plugin/   示例外部插件
  plugin-market/    本地插件市场包
  .agents/skills/   项目级 Codex Skills
```

## 插件市场

当前本地插件市场位于 `plugin-market/`。查看每个插件的详细用途、能力、依赖和配置说明：[插件功能目录](./docs/plugins.md)。

| 插件 ID | 名称 | 类型 | 主要作用 |
| --- | --- | --- | --- |
| `agent.loop.react` | ReAct 智能体循环 | Agent Loop | 基于模型、工具、记忆、Skills 和 MCP 工具上下文运行智能体对话。 |
| `agent.loop.codex_bridge` | Codex Bridge | Agent Loop | 调用本地 `codex exec` 执行任务并桥接流式输出。 |
| `agent.loop.claude_code_bridge` | Claude Code Bridge | Agent Loop | 调用本地 `claude --print` 执行任务并桥接流式输出。 |
| `context.manager` | 上下文管理器 | 上下文 | 编排上下文压缩并生成后续模型消息。 |
| `context.compressor.summary` | 上下文摘要压缩 | 上下文 | 不依赖模型的轻量摘要压缩。 |
| `context.compressor.model` | 模型上下文摘要压缩 | 上下文 | 使用模型生成上下文续跑摘要。 |
| `memory.file` | 文件记忆 | 记忆 | 用本地 JSONL 文件保存和检索记忆。 |
| `skill.registry` | 技能注册表 | 技能 | 加载本地 `SKILL.md`，提供技能列表、激活和文件读取能力。 |
| `tool.runtime` | 工具运行时 | 工具运行时 | 发现工具、校验参数并路由工具调用。 |
| `tool.basic` | 基础工具集 | 工具 | 提供 echo、当前时间、数字相加等基础工具。 |
| `tool.http_request` | HTTP 请求工具 | 工具 | 调用固定 HTTP 端点或受限 Raw HTTP 请求。 |
| `workspace.sandbox` | 代码沙盒 | 工具 | 在隔离目录内读写文件、搜索和执行受限命令。 |
| `mcp.bridge` | MCP 桥接器 | MCP | 将 stdio MCP 服务工具桥接到 Agent 工具系统。 |
| `model.openai_compatible` | OpenAI 兼容模型 | 模型 | 接入 OpenAI Chat Completions 兼容服务。 |
| `model.openrouter` | OpenRouter 模型 | 模型 | 通过 OpenRouter 调用多家模型。 |
| `model.deepseek` | DeepSeek 模型 | 模型 | 通过 DeepSeek API 调用 DeepSeek 模型。 |

## 开发新插件

插件是 Agent 能力的唯一扩展单元。第三方插件应该只依赖公共 SDK `plugin_agent_sdk`，通过 capability 与其他插件协作，不直接导入后端私有内核代码。可以从 [example-plugin](./example-plugin) 复制一个最小工具插件开始，参考 [plugin-market/http-tool-plugin](./plugin-market/http-tool-plugin) 了解带配置、密钥 header 和外部请求的工具插件，也可以参考面向 Agent 的插件开发 Skill：[develop-plugin-agent-plugins](./.agents/skills/develop-plugin-agent-plugins/SKILL.md)。

### 1. 准备插件包

插件开发者只需要准备一个本地插件包目录，目录名可以任意，最小结构如下：

```text
your-plugin/
  plugin.yaml
  config.yaml       # 可选：默认配置
  plugin.py
```

`example-plugin/` 是一个最小工具插件示例。`plugin-market/http-tool-plugin/` 是一个更完整的 HTTP 集成工具示例，包含固定端点、可选 Raw 请求、普通 header、敏感 header、host allowlist 和响应解析。开发新插件时，可以复制最接近的示例到任意工作目录后改名：

复杂插件可以继续在目录内增加 Python 模块或子包，让 `plugin.py` 只保留入口类和 capability 路由，例如 `workspace.sandbox` 把文件读写、搜索和命令执行拆在 `workspace_tools/` 下。

```bash
cp -R example-plugin ~/my-plugin
```

不要手动修改后端运行时目录或仓库内的插件市场目录；插件进入系统应通过前端“上传插件包”按钮完成。

### 2. 声明插件契约

`plugin.yaml` 是插件的公开契约，至少要声明：

- `descriptor.id` / `version` / `name` / `description`：包身份和展示信息。
- `runtime.type: python.in_process` 和 `runtime.entrypoint: plugin.py:<PluginClass>`：运行时入口。
- `provides`：插件提供的 capability 名称、版本、输入/输出 schema 引用。
- `requires`：插件依赖的其他 capability，标明 `required: true/false`。
- `resources`：给 UI 和 Agent Loop 发现的语义资源，例如 `kind: tool`。
- `schemas`：所有输入、输出、配置 schema。除非刻意开放，建议 `additionalProperties: false`。

能力命名使用点分命名空间，例如 `tool.weather_current`、`memory.query`、`context.compress`。schema ref 使用稳定 URI，例如 `schema://tool.weather_current.input.v1`。

### 3. 实现运行时代码

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

### 4. 验证和安装

开发阶段可以先运行后端测试确认 SDK 和插件市场链路没有被破坏：

```bash
cd backend
uv run pytest tests/test_plugin_market.py -q
uv run pytest -q
```

本地调试时启动控制台，进入“插件市场”，点击“上传插件包”，选择插件目录或打包后的 `.pluginpkg`。上传完成后在插件市场安装插件，再到 Agent 工作台中为 Agent 添加并配置插件实例。如果只想验证上传链路，可以直接上传 `example-plugin/`；HTTP 请求工具已经作为本地市场包提供，可直接在插件市场安装后配置 `endpoints`、`security.allowed_hosts` 和 `secret_headers`。

## 参考文档

- [插件功能目录](./docs/plugins.md)
- [后端指南](./backend/README.md)
- [前端协作说明](./frontend/AGENTS.md)
- [Docker 部署说明](./docker/README.md)
- [项目协作规则](./AGENTS.md)
- [后端开发规则](./backend/AGENTS.md)
- [项目文档维护 Skill](./.agents/skills/maintain-project-docs/SKILL.md)

## 验证命令

```bash
cd backend && uv run pytest -q
cd frontend && yarn build
docker compose -f docker/docker-compose.yml config
```

## 许可证

本项目使用 [Apache License 2.0](./LICENSE)。
