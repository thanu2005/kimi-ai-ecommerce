"""MCP tool modules — one file per agent domain.

Each module exposes a ``register(mcp: FastMCP) -> None`` function that
decorates and registers all tools for that domain onto the shared FastMCP
instance created in ``mcp_server.server``.
"""
