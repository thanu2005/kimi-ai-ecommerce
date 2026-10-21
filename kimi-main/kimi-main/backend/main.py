"""FastAPI application entrypoint.

Startup lifecycle
-----------------
1. ``create_db_and_tables()`` — ensures all SQLModel tables exist in Postgres.
2. ``AsyncPostgresSaver`` is initialised and stored on ``app.state`` for use
   by the graph invocation endpoints.

API surface
-----------
POST /api/run
    Trigger a full analysis run.  Accepts an optional ``product_focus_id``
    and ``thread_id``.  Returns the whiteboard and proposed_actions after
    the graph hits the HITL interrupt barrier.

POST /api/resume
    Resume a paused graph after operator review.  Accepts the modified
    ``proposed_actions`` list and the ``thread_id`` to restore from.

GET  /health
    Liveness probe used by Docker / load balancers.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import settings
from app.db.session import create_db_and_tables
from app.routes import analysis_router, conversations_router, health_router
from app.services.observability import configure_langsmith

if sys.platform.startswith("win"):
    # psycopg async requires SelectorEventLoop on Windows.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Configure logging so agent progress appears in the uvicorn terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Lifespan                                                                    #
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    # 1. Ensure DB tables exist
    await create_db_and_tables()

    # 2. Configure LangSmith tracing for LangChain / LangGraph runs
    app.state.langsmith_client = configure_langsmith()

    # 3. Initialise Postgres checkpointer for HITL graph persistence
    async with AsyncPostgresSaver.from_conn_string(
        settings.sync_database_url
    ) as checkpointer:
        await checkpointer.setup()
        app.state.checkpointer = checkpointer

        # 4. Build and cache the supervisor graph
        from app.agents.orchestrator import build_supervisor_graph
        app.state.graph = build_supervisor_graph(checkpointer=checkpointer)

        yield


# --------------------------------------------------------------------------- #
#  App instance                                                                #
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="AI E-Commerce Operations Brain",
    version="0.1.0",
    description="Multi-agent LangGraph backend with HITL checkpointing.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(analysis_router)
app.include_router(conversations_router)

