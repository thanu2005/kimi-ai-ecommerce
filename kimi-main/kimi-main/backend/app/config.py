"""Application configuration — Pydantic BaseSettings environment loader."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so it is found regardless of CWD.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Loads all runtime configuration from environment variables or a .env file.

    Pydantic validates every field at import time, so a missing or malformed
    environment variable raises an error before the application starts.
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ #
    #  PostgreSQL (asyncpg DSN)                                            #
    # ------------------------------------------------------------------ #
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_host: str = "localhost"
    postgres_port: int = 5454
    postgres_db: str = "ecommerce_ops"

    @property
    def database_url(self) -> str:
        """Async DSN consumed by SQLAlchemy's asyncpg engine."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Sync DSN required by LangGraph's AsyncPostgresSaver checkpointer init."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ------------------------------------------------------------------ #
    #  Qdrant                                                              #
    # ------------------------------------------------------------------ #
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "support_ticket_embeddings"
    qdrant_agent_memory_collection: str = "agent_run_memories"

    # ------------------------------------------------------------------ #
    #  LLM / LangSmith                                                     #
    # ------------------------------------------------------------------ #
    dial_api_key: str
    # Azure AI Foundry DIAL gateway settings
    dial_endpoint: str = "https://ai-proxy.lab.epam.com"
    dial_api_version: str = "2025-04-01-preview"
    # Azure deployment name for the chat LLM
    dial_chat_deployment: str = "claude-sonnet-4-5@20250929"
    # Azure deployment name for the text-embedding model
    dial_embedding_deployment: str = "text-embedding-3-small-1"
    langsmith_api_key: str = ""
    langsmith_tracing: bool = True
    langsmith_project: str = "ecommerce-ops-brain"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # ------------------------------------------------------------------ #
    #  MCP server (SSE transport)                                          #
    # ------------------------------------------------------------------ #
    # URL of the externally-started FastMCP SSE server.  Start the server
    # manually in a terminal (from the project root):
    #   fastmcp run mcp_server/server.py:mcp --transport sse --port 8001
    # then set MCP_SSE_URL=http://localhost:8001/sse in your .env.
    # Leave blank to fall back to per-agent stdio subprocesses.
    mcp_sse_url: str = ""

    # ------------------------------------------------------------------ #
    #  FastAPI                                                             #
    # ------------------------------------------------------------------ #
    app_env: str = "development"   # development | production
    app_debug: bool = True


# Module-level singleton — import `settings` wherever config is needed.
settings = Settings()
