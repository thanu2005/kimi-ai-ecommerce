# ── Stage 1: dependency install via uv ────────────────────────────────────
FROM python:3.12-slim AS builder

# Pull the uv binary from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency manifest and lockfile first for layer-cache efficiency
COPY pyproject.toml uv.lock* ./

# Install production dependencies into the project virtual environment
RUN uv sync --frozen --no-dev

# ── Stage 2: runtime image ────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Bring the pre-built venv across from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY . .

# Make the venv the active Python environment
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
