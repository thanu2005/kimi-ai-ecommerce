FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app/mcp_server

COPY mcp_server/pyproject.toml mcp_server/uv.lock* ./
RUN uv sync --no-dev

FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY --from=builder /app/mcp_server/.venv /app/mcp_server/.venv
COPY mcp_server ./mcp_server
COPY backend/app ./backend/app

ENV PATH="/app/mcp_server/.venv/bin:$PATH"
ENV PYTHONPATH="/app:/app/backend"

EXPOSE 8002

CMD ["python", "mcp_server/start_server.py", "--host", "0.0.0.0", "--port", "8002"]
