"""FastMCP server — single entry-point for all agent tools.

Architecture
------------
- One shared ``FastMCP`` instance (``mcp``) is created here.
- Each domain's tools live in ``tools/<domain>.py`` and are registered by
  calling their ``register(mcp)`` function below.
- The server lives at the project root (``mcp_server/``) and is completely
  independent of the FastAPI backend.  Start it once in its own terminal::

      cd mcp_server
      fastmcp run server.py:mcp --transport sse --port 8001

  or from the project root::

      fastmcp run mcp_server/server.py:mcp --transport sse --port 8001

Transport
---------
The server respects the ``FASTMCP_TRANSPORT`` environment variable
(default: ``stdio`` when run directly).  No code change is required to
switch transports.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the backend package (app.*, app.db.*, app.config) is importable.
# The tools in this folder import from `app.*` which lives in backend/.
# We insert backend/ onto sys.path here so this server can run from any cwd.
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

for _p in (str(_PROJECT_ROOT), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastmcp import FastMCP

# --------------------------------------------------------------------------- #
#  Tool invocation logging middleware                                          #
# --------------------------------------------------------------------------- #

import json
from functools import wraps
from typing import Any

def wrap_tool_with_logging(tool_func, tool_name: str):
    """Wrap a tool function to log invocations and results."""
    @wraps(tool_func)
    async def logged_tool(*args, **kwargs) -> Any:
        # Log tool invocation
        log.info(f"🔧 [TOOL INVOKED] Tool: {tool_name}")
        log.info(f"   └─ Parameters: {json.dumps(kwargs, default=str)}")
        
        try:
            result = await tool_func(*args, **kwargs)
            
            # Log tool result (preview first 300 chars)
            result_str = json.dumps(result, default=str) if not isinstance(result, str) else result
            preview = result_str[:300] + ("..." if len(result_str) > 300 else "")
            log.info(f"✅ [TOOL SUCCESS] Tool: {tool_name}")
            log.info(f"   └─ Result: {preview}")
            
            return result
        except Exception as e:
            log.error(f"❌ [TOOL ERROR] Tool: {tool_name}")
            log.error(f"   └─ Error: {str(e)}")
            raise
    
    return logged_tool

# Silence all loggers that write to stdout — the stdio MCP transport uses
# stdout exclusively for JSON-RPC; any non-JSON bytes corrupt the protocol.
logging.getLogger("sqlalchemy").setLevel(logging.CRITICAL)
logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)
logging.getLogger("asyncpg").setLevel(logging.CRITICAL)

# Redirect root logger to stderr so nothing accidentally hits stdout
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger(__name__)

from mcp_server.tools.inventory import register as register_inventory
from mcp_server.tools.memory import register as register_memory
from mcp_server.tools.marketing import register as register_marketing
from mcp_server.tools.sales import register as register_sales
from mcp_server.tools.support import register as register_support

# --------------------------------------------------------------------------- #
#  Shared MCP application                                                      #
# --------------------------------------------------------------------------- #

mcp = FastMCP(
    name="ecommerce-ops-brain",
    instructions=(
        "You are the tool layer for the AI E-Commerce Operations Brain. "
        "All tools are read-only during agent analysis cycles except for the "
        "action tools (update_safety_stock_trigger, restock_product_emergency) "
        "which must only be invoked from the HITL execute_approved_actions node "
        "after explicit operator approval."
    ),
)

# --------------------------------------------------------------------------- #
#  Tool registration — one call per domain module                              #
# --------------------------------------------------------------------------- #

register_inventory(mcp)
register_sales(mcp)
register_marketing(mcp)
register_support(mcp)
register_memory(mcp)

# --------------------------------------------------------------------------- #
#  Entry point (stdio transport for LangGraph subprocess connection)           #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    mcp.run()
