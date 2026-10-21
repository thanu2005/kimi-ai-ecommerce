"""LangSmith observability helpers.

Provides one place to configure LangSmith runtime settings and to create
trace contexts for graph executions so nested LangGraph / LangChain calls
inherit the same project, metadata, and tags.
"""

from __future__ import annotations

import os
from contextlib import contextmanager, nullcontext
from typing import Any, Iterator

from langsmith import Client
from langsmith.run_helpers import tracing_context

from app.config import settings


def configure_langsmith() -> Client | None:
    """Configure process-level LangSmith environment and return a client.

    Returns ``None`` when tracing is disabled or no API key is configured.
    """
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return None

    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project

    return Client(
        api_key=settings.langsmith_api_key,
        api_url=settings.langsmith_endpoint,
    )


@contextmanager
def graph_trace_context(
    *,
    client: Client | None,
    operation: str,
    thread_id: str,
    run_id: str,
    metadata: dict[str, Any] | None = None,
) -> Iterator[None]:
    """Create a LangSmith tracing context for one API-level graph execution."""
    if client is None:
        yield from nullcontext()
        return

    trace_metadata = {
        "thread_id": thread_id,
        "run_id": run_id,
        "operation": operation,
        **(metadata or {}),
    }
    with tracing_context(
        enabled=True,
        client=client,
        project_name=settings.langsmith_project,
        tags=["backend", "langgraph", operation],
        metadata=trace_metadata,
    ):
        yield