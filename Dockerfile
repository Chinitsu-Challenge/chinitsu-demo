# syntax=docker/dockerfile:1.7

# --- Stage 1: build Svelte frontend ---
FROM node:22-alpine AS frontend
WORKDIR /app/web-svelte
COPY web-svelte/package.json web-svelte/package-lock.json ./
RUN npm ci
COPY web-svelte/ ./
RUN npm run build

# --- Stage 2: install Python deps with uv ---
FROM python:3.12-slim AS backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# --- Stage 3: final runtime ---
FROM python:3.12-slim
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /app/web-svelte/build /app/web-svelte/build
COPY server/ /app/server/
COPY docs/ /app/docs/

# SQLite DB is written to /app/chinitsu.db by server/database.py.
# To persist across container recreations, bind-mount it on the host, e.g.:
#   docker run -v /srv/chinitsu/chinitsu.db:/app/chinitsu.db ghcr.io/.../chinitsu-demo
EXPOSE 8000
WORKDIR /app/server
CMD ["python", "start_server.py"]
