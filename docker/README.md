# Docker Deployment

Run from this directory:

```bash
cp .env.example .env
docker compose up --build
```

Open the console at:

```text
http://127.0.0.1:8080
```

Backend data is persisted under `docker/volumes/plugin-agent-data` by default.
The image includes the repository `plugin-market/` directory at `/app/plugin-market`.
Set `PLUGIN_AGENT_MARKET_DIR` if you need to point the backend at another marketplace path.

Useful checks:

```bash
docker compose config
docker compose build backend
docker compose build frontend
```
