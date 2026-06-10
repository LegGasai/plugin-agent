# 插件功能目录

本文列举 `plugin-market/` 中当前提供的插件包，帮助用户选择、安装和配置 Agent 能力。插件安装后会成为 Agent 可添加的插件实例；多个插件提供同名 capability 时，需要在 Agent 配置中选择实际 provider。

## 快速选择

| 插件 ID | 名称 | 类型 | 适合场景 |
| --- | --- | --- | --- |
| `agent.loop.react` | ReAct 智能体循环 | Agent Loop | 让 Agent 使用模型、工具、记忆、Skills、MCP 工具和上下文能力完成多轮任务。 |
| `agent.loop.codex_bridge` | Codex Bridge | Agent Loop | 把任务交给本地 Codex CLI 执行，并把 JSONL 输出流式桥接到控制台。 |
| `agent.loop.claude_code_bridge` | Claude Code Bridge | Agent Loop | 把任务交给本地 Claude Code CLI 执行，并把 stream-json 输出流式桥接到控制台。 |
| `context.manager` | 上下文管理器 | 上下文 | 统一调用压缩 provider，并把压缩结果转换为后续模型消息。 |
| `context.compressor.summary` | 上下文摘要压缩 | 上下文 | 不依赖模型的简短摘要压缩，适合轻量默认配置。 |
| `context.compressor.model` | 模型上下文摘要压缩 | 上下文 | 使用已绑定模型生成质量更高的上下文摘要。 |
| `memory.file` | 文件记忆 | 记忆 | 用本地 JSONL 文件保存和检索 Agent 记忆。 |
| `skill.registry` | 技能注册表 | 技能 | 加载本地 `SKILL.md`，提供技能列表、激活和文件读取能力。 |
| `tool.runtime` | 工具运行时 | 工具运行时 | 发现工具资源、校验参数并路由 `tool.invoke`。 |
| `tool.basic` | 基础工具集 | 工具 | 提供 echo、当前时间和数字相加等基础工具。 |
| `tool.http_request` | HTTP 请求工具 | 工具 | 调用固定 HTTP 端点，或显式启用受限 Raw HTTP 请求。 |
| `workspace.sandbox` | 代码沙盒 | 工具 | 在指定工作区内进行文件读写、搜索和受限命令执行。 |
| `mcp.bridge` | MCP 桥接器 | MCP | 将 stdio MCP 服务工具桥接到 Agent 工具系统。 |
| `model.openai_compatible` | OpenAI 兼容模型 | 模型 | 接入任意 OpenAI Chat Completions 兼容服务。 |
| `model.openrouter` | OpenRouter 模型 | 模型 | 通过 OpenRouter 调用多家模型。 |
| `model.deepseek` | DeepSeek 模型 | 模型 | 通过 DeepSeek OpenAI-compatible API 调用 DeepSeek 模型。 |

## 插件详情

### `agent.loop.react` - ReAct 智能体循环

- 作用：基于模型推理、工具发现、工具调用、记忆读取、Skills 目录提示和 MCP 工具上下文运行 Agent 对话。
- 提供能力：`agent.run`、`agent.stream`。
- 必需依赖能力：`model.chat`、`memory.query`、`memory.write`、`tool.registry.list`、`tool.invoke`。
- 可选增强能力：`skill.list`、`skill.activate`、`skill.read_file`、`mcp.tools.list`。缺失时 Agent 仍可启动；调用失败默认发出运行时告警并继续。
- 资源：`agent_loop: react`。
- 配置要点：可设置 system prompt；可配置最大推理轮数、工具调用超时、触发上下文压缩的消息阈值；v2 还支持配置 Skills 目录提示、工具提示开关、MCP 工具目录提示和失败策略。
- 使用建议：通常每个可对话 Agent 至少需要一个 Agent Loop。若要流式聊天，应优先搭配提供 `model.chat.stream` 的模型插件。

### `agent.loop.codex_bridge` - Codex Bridge

- 作用：调用本地 `codex exec --json`，把 Codex JSONL 事件转换为 `agent.stream` 事件。
- 提供能力：`agent.run`、`agent.stream`。
- 依赖能力：无。
- 资源：`agent_loop: codex_bridge`。
- 配置要点：必须配置 `workspace_root`；可配置 `command`、`model`、`profile`、`sandbox`、`timeout_ms`、`extra_args` 和环境变量。
- 权限说明：`bypass_approvals_and_sandbox` 会传递 `--dangerously-bypass-approvals-and-sandbox`，仅应在外层已有可靠沙箱时启用。
- 使用建议：适合本地项目 coding Agent。若同一 Agent 还安装了其他 Agent Loop，需要绑定 `agent.run` / `agent.stream` provider。

### `agent.loop.claude_code_bridge` - Claude Code Bridge

- 作用：调用本地 `claude -p --verbose --output-format stream-json`，把 Claude Code 输出转换为 `agent.stream` 事件。
- 提供能力：`agent.run`、`agent.stream`。
- 依赖能力：无。
- 资源：`agent_loop: claude_code_bridge`。
- 配置要点：必须配置 `workspace_root`；可配置 `command`、`model`、`permission_mode`、`allowed_tools`、`disallowed_tools`、`timeout_ms`、`extra_args` 和环境变量。
- 权限说明：`dangerously_skip_permissions` 会传递 `--dangerously-skip-permissions`，仅应在外层已有可靠沙箱时启用。
- 使用建议：适合复用本机 Claude Code 能力处理项目任务。若同一 Agent 还安装了其他 Agent Loop，需要绑定 `agent.run` / `agent.stream` provider。

### `context.manager` - 上下文管理器

- 作用：编排上下文压缩，将压缩摘要和尾部消息组合成可继续推理的模型消息。
- 提供能力：`context.compress`。
- 依赖能力：`context.compressor.compress`。
- 资源：`context: manager`。
- 配置要点：可设置保留尾部消息数量和摘要前缀。
- 使用建议：推荐让 Agent Loop 调用 `context.compress`，再由上下文管理器绑定具体压缩 provider。

### `context.compressor.summary` - 上下文摘要压缩

- 作用：将较长对话上下文压缩为简短摘要，不依赖外部模型。
- 提供能力：`context.compressor.compress`。
- 依赖能力：无。
- 资源：`context: summary`。
- 配置要点：可设置最大摘要字符数。
- 使用建议：适合作为默认、低成本、无模型依赖的压缩 provider。

### `context.compressor.model` - 模型上下文摘要压缩

- 作用：调用已绑定模型 provider，把较长上下文压缩为续跑摘要。
- 提供能力：`context.compressor.compress`。
- 依赖能力：`model.chat`。
- 资源：`context: model-summary`。
- 配置要点：可设置最大摘要字符数和压缩 system prompt。
- 使用建议：与 `context.compressor.summary` 同时安装时，两者都提供 `context.compressor.compress`，需要在 Agent 的能力绑定界面选择实际 provider。

### `memory.file` - 文件记忆

- 作用：使用本地 JSONL 文件保存和检索 Agent 记忆。
- 提供能力：`memory.write`、`memory.query`。
- 依赖能力：无。
- 资源：`memory: file`。
- 配置要点：可设置记忆文件路径；未显式配置时，后端会为 Agent 生成运行时记忆文件路径。
- 使用建议：适合本地开发和轻量记忆验证；生产环境可后续替换成数据库或向量存储插件。

### `skill.registry` - 技能注册表

- 作用：加载本地 `SKILL.md` 技能文件，并提供技能列表、激活和文件读取能力。
- 提供能力：`skill.list`、`skill.activate`、`skill.read_file`。
- 依赖能力：无。
- 资源：`skill: registry`。
- 配置要点：可配置 `skill_dirs`，指向一个或多个技能目录。
- 工具资源：`activate_skill` 返回指定 Skill 的元数据和文件树；`read_skill_file` 读取指定 Skill 目录内的普通文件，禁止路径逃逸。
- 使用建议：Agent Loop 先通过 `skill.list` 将可用 Skills 的名称和描述注入模型上下文；模型判断需要某个 Skill 时，再调用 `activate_skill` 和 `read_skill_file` 按需读取。

### `tool.runtime` - 工具运行时

- 作用：统一发现所有 `kind: tool` 资源，校验输入 schema，并把 `tool.invoke` 路由到实际工具 provider。
- 提供能力：`tool.registry.list`、`tool.invoke`。
- 依赖能力：无。
- 资源：`tool_runtime: default`。
- 配置要点：包含工具审计开关。
- 使用建议：只要 Agent 需要调用工具，就应安装工具运行时。具体工具插件通常依赖它。

### `tool.basic` - 基础工具集

- 作用：提供基础演示工具。
- 提供能力：`tool.echo`、`tool.time_now`、`tool.math_add`。
- 依赖能力：`tool.invoke`。
- 资源：`tool: echo`、`tool: time.now`、`tool: math.add`。
- 配置要点：可设置默认时区。
- 使用建议：适合验证工具注册、工具调用和 Agent Loop 工具链路。

### `tool.http_request` - HTTP 请求工具

- 作用：发起受限 HTTP 请求，支持用户预先配置固定端点，也支持显式开启 Raw 请求。
- 提供能力：`tool.http_endpoint_request`、`tool.http_raw_request`。
- 依赖能力：`tool.invoke`。
- 资源：`tool: http.endpoint_request`、`tool: http.raw_request`。
- 配置要点：
  - `endpoints` 配置固定端点，端点内可设置 `method`、`url_template`、`query_template`、`body_template`、`headers`、`secret_headers`。
  - `secret_headers` 用于保存 `Authorization` 等敏感 header，会按 schema 加密和脱敏。
  - `security.allowed_hosts`、`security.allowed_schemes`、`security.allowed_methods` 控制请求边界。
  - `security.allow_raw_requests` 默认为 `false`；关闭时 Raw 工具不会暴露给 Agent。
  - 默认禁止访问私网/本机地址；本地测试需要显式打开 `security.allow_private_networks`。
- 使用建议：固定端点模式适合飞书通知、Webhook、内部系统回调等场景；Raw 模式仅建议给可信 Agent 或受控环境开启。

### `workspace.sandbox` - 代码沙盒

- 作用：在指定工作区内提供文件列表、读取、写入、局部编辑、搜索、glob 和受限命令执行工具。
- 提供能力：`workspace.ls`、`workspace.read`、`workspace.write`、`workspace.edit`、`workspace.grep`、`workspace.glob`、`workspace.bash`。
- 依赖能力：无。
- 资源：`tool: workspace.ls`、`tool: workspace.read`、`tool: workspace.write`、`tool: workspace.edit`、`tool: workspace.grep`、`tool: workspace.glob`、`tool: workspace.bash`。
- 配置要点：
  - 必填 `workspace_root`，所有文件操作应限制在该目录内。
  - `sandbox.command_timeout_ms`、`sandbox.max_output_bytes` 控制命令执行资源。
  - `sandbox.allowed_commands`、`sandbox.denied_patterns` 可约束命令策略。
  - `filesystem.max_file_bytes`、`filesystem.protected_paths` 控制文件读取和保护路径。
- 使用建议：适合构建代码助手、文件整理 Agent 和项目内自动化工具；配置时应尽量缩小工作区范围。

### `mcp.bridge` - MCP 桥接器

- 作用：启动并连接 stdio MCP 服务，将 MCP 工具桥接成 Agent 可调用工具。
- 提供能力：`mcp.tools.list`、`mcp.tool.call`。
- 依赖能力：`tool.invoke`。
- 资源：`mcp_server: bridge`。
- 配置要点：`servers` 中配置 MCP 服务的 `name`、`command`、`args`、`env`；可设置 `request_timeout_seconds`。
- 使用建议：适合把已有 MCP server 的工具接入 Agent，不需要为每个工具单独写插件。

### `model.openai_compatible` - OpenAI 兼容模型

- 作用：调用兼容 OpenAI Chat Completions API 的模型服务。
- 提供能力：`model.chat`、`model.chat.stream`。
- 依赖能力：无。
- 资源：`model: openai_compatible`。
- 配置要点：需要配置 `api_key`、`base_url`、`model` 和请求超时；`api_key` 为加密密钥字段。
- 使用建议：适合接入本地模型网关、OpenAI-compatible 私有服务或代理服务。

### `model.openrouter` - OpenRouter 模型

- 作用：通过 OpenRouter 的 OpenAI-compatible API 调用多家模型。
- 提供能力：`model.chat`、`model.chat.stream`。
- 依赖能力：无。
- 资源：`model: openrouter`。
- 配置要点：需要配置 `api_key`、`base_url`、`model` 和请求超时；默认 base URL 指向 OpenRouter。
- 使用建议：适合在一个 provider 内切换不同模型供应商。与其他模型插件共存时，需要绑定 `model.chat` provider。

### `model.deepseek` - DeepSeek 模型

- 作用：通过 DeepSeek 的 OpenAI-compatible API 调用 DeepSeek 模型。
- 提供能力：`model.chat`、`model.chat.stream`。
- 依赖能力：无。
- 资源：`model: deepseek`。
- 配置要点：需要配置 `api_key`、`base_url`、`model` 和请求超时；默认 base URL 指向 DeepSeek。
- 使用建议：适合直接使用 DeepSeek 模型。与 OpenRouter 或其他模型插件共存时，需要绑定 `model.chat` provider。
