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

- 插件市场：通过 `plugin-market/` 模拟本地插件市场，支持上传、安装、卸载和版本化安装插件包。
- Agent 装配：每个 Agent 都由独立插件实例组成，配置、密钥引用、生命周期和版本互不干扰。
- 能力路由：插件通过 `Capability` 调用彼此，内核负责 provider 选择、schema 校验、错误诊断和流式调用。
- 可视化控制台：React 控制台提供插件市场、Agent 广场、工作台、插件配置、会话列表和流式聊天。
- 运行时诊断：当模型配置缺失、依赖能力缺失或多个 provider 冲突时，后端会给出 Agent 运行时报告。
- 会话与记忆：会话历史由主机持久化，长期记忆由插件提供，Agent Loop 可以同时使用两者。
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

Docker 会把仓库内的 `plugin-market/` 复制进后端镜像，并把运行时数据持久化到 `docker/volumes/plugin-agent-data`。

### 本地开发启动

后端：

```bash
cd backend
uv run plugin-agent serve --host 127.0.0.1 --port 8000
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
  plugin-market/    本地插件市场
  test-plugin/      示例外部插件
  .agents/skills/   项目级 Codex Skills
```

## 参考文档

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
