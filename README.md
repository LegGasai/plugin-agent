# plugin-agent

Lightweight pluginized Agent platform in a small monorepo.

## Structure

```text
plugin-agent/
  backend/    # Python Agent kernel, SDK, plugins, HTTP API, CLI
  frontend/   # React console
  docker/     # Docker Compose deployment files
  plugin-market/ # local marketplace plugin packages for development-time install simulation
  test-plugin/ # sample external plugin package for upload/install smoke checks
  .agents/skills/ # project-local Codex skills
  AGENTS.md   # root guidance for future agents
```

The backend owns plugin lifecycle, capability discovery, capability routing, schema validation, plugin instances, agents, streaming runs, and persistence. Plugin packages declare their config schema, plugin instances store their own config and local secret refs, and the frontend is the operator console for plugin market, agent square, plugin instance configuration, provider binding, and streaming chat runtime.

During local development, `plugin-market/` simulates a remote marketplace. The previously built plugins now live there as unpacked plugin packages, uploaded `.pluginpkg` files are copied there, and installed plugins are unpacked into `.plugin-agent/installed-plugins/`. Installed packages are stored by `package_id/version`, and Agent plugin instances pin the selected version. When an installed package has the same `package_id` as a built-in compatibility plugin, the installed package is loaded first.

`test-plugin/` is a small external greeter plugin used for manual upload/install checks without touching backend private plugin code.

## Quickstart

Backend:

```bash
cd backend
uv run plugin-agent serve --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
yarn install
yarn dev --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173
```

Docker:

```bash
cd docker
cp .env.example .env
docker compose up --build
```

Open:

```text
http://127.0.0.1:8080
```

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

Docker config:

```bash
docker compose -f docker/docker-compose.yml config
```

## More Docs

- [Root agent guidance](./AGENTS.md)
- [Backend guide](./backend/README.md)
- [Backend agent guidance](./backend/AGENTS.md)
- [Frontend agent guidance](./frontend/AGENTS.md)
- [Docker deployment guide](./docker/README.md)
- [Project docs maintenance skill](./.agents/skills/maintain-project-docs/SKILL.md)
