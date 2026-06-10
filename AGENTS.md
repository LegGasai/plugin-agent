# Root AGENTS.md

This repository is a small monorepo for a lightweight pluginized Agent platform.

## Subrepos

- `backend/`
  - Python Agent kernel, product services/stores, public plugin SDK, built-in plugins, HTTP API, CLI, and tests.
  - Read `backend/AGENTS.md` before changing backend code.
- `frontend/`
  - React console for plugin market, agent square, plugin instance configuration, provider binding, session history, and streaming chat runtime.
  - Read `frontend/AGENTS.md` before changing frontend code.
- `docker/`
  - Docker Compose deployment for backend plus Nginx-served frontend.
  - Backend images copy the root `plugin-market/` into `/app/plugin-market`.
- `docs/`
  - User-facing project and plugin documentation.
- `.agents/skills/`
  - Project-local Codex skills for repeatable workflows.
  - Use `.agents/skills/maintain-project-docs` when code or structure changes require README/AGENTS updates.
- `plugin-market/`
  - Development-time local marketplace for upload/install simulation.
  - Internal storage backing the frontend upload/install flow.
  - Keep generated `.pluginpkg` artifacts out of git.
- `example-plugin/`
  - Small external greeter plugin package for upload/install smoke checks.
- `plugin-market/http-tool-plugin/`
  - Local marketplace HTTP tool plugin package demonstrating configured endpoints, secret headers, and optional raw requests.

Root-level coordination files and directories:

- `README.md`
- `AGENTS.md`
- `.gitignore`
- `.dockerignore`
- `docker/`
- `docs/`
- `example-plugin/`
- `plugin-market/.gitkeep`
  - Plugin package directories under `plugin-market/`

Do not add backend source, backend tests, or frontend source files at the repository root.

## Core Product Boundaries

- The backend kernel is the private host/runtime.
- Backend product logic is layered under `backend/src/plugin_agent/services/`, `stores/`, `models/`, and `utils/`; keep `backend/src/plugin_agent/assembly.py` as a compatibility facade.
- `backend/src/plugin_agent_sdk/` is the public plugin SDK surface.
- Third-party plugins should depend on the SDK, not private kernel implementation.
- User-facing plugin installation should go through the frontend upload/install flow; default product plugins are auto-installed from `plugin-market/` into the runtime installed-plugin directory.
- `backend/src/plugin_agent/plugins/` is for host compatibility implementations and direct provider tests, not the product package registry.
- The frontend should consume backend HTTP APIs through `frontend/src/lib/api.js`.

## Verification

Backend:

```bash
cd backend
uv run pytest -q
```

Frontend:

```bash
cd frontend
yarn build
```

If a change touches both subrepos, run both commands.

Docker:

```bash
docker compose -f docker/docker-compose.yml config
```

## Local Development

Backend:

```bash
cd backend
uv run plugin-agent serve --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
yarn dev --host 127.0.0.1 --port 5173
```

## Change Discipline

- Keep backend and frontend concerns separated.
- Update the matching subrepo `AGENTS.md` when changing conventions.
- Use Yarn for the frontend; do not add `package-lock.json`.
- Preserve the plugin product model: `PluginPackage`, `PluginInstance`, `Agent`, `Session`, `Capability`, and `Resource`.
- Preserve Agent-level `capability_bindings`; do not store provider choices in plugin config.
- Preserve the frontend fixed-viewport console layout unless the user explicitly asks for a broader redesign.
- Do not commit runtime state such as `.plugin-agent/`, `.venv/`, `.pytest_cache/`, `frontend/node_modules/`, or `frontend/dist/`.
- Do not commit uploaded plugin package artifacts from `plugin-market/`.
