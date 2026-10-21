"""Standalone launcher for the MCP SSE server.

Starts the FastMCP server on SSE transport using uvicorn directly,
bypassing the `fastmcp run` CLI which has known issues on Windows.

Usage (from project root):
    python mcp_server/start_server.py
    python mcp_server/start_server.py --port 8002

Usage (from mcp_server/):
    python start_server.py
    python start_server.py --port 8002
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure backend packages (app.*, app.config, etc.) are importable.
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent / "backend"
_PROJECT_ROOT = _SCRIPT_DIR.parent

for _p in (str(_PROJECT_ROOT), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from server import mcp  # noqa: E402 (sys.path must be patched first)

import uvicorn  # noqa: E402
from fastmcp.server.http import create_sse_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the MCP SSE server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8002, help="Port to listen on")
    args = parser.parse_args()

    app = create_sse_app(mcp, message_path="/messages", sse_path="/sse")
    print(f"Starting MCP SSE server on http://{args.host}:{args.port}")
    print(f"  SSE endpoint : http://localhost:{args.port}/sse")
    print(f"  Messages path: http://localhost:{args.port}/messages")
    print("Press Ctrl+C to stop.\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
