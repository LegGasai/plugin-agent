FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/src ./src
RUN uv sync --frozen --no-dev

FROM python:3.11-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PLUGIN_AGENT_MARKET_DIR=/app/plugin-market

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY backend/src ./src
COPY plugin-market ./plugin-market

RUN mkdir -p /app/.plugin-agent

EXPOSE 8000

CMD ["plugin-agent", "serve", "--host", "0.0.0.0", "--port", "8000"]
