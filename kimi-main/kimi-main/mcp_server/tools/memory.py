"""Memory-domain MCP tools.

Read-only tools that expose long-term incident memory and action-effectiveness
analytics from Postgres + Qdrant.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def register(mcp) -> None:
    """Register memory-domain tools onto the shared FastMCP instance.

    Parameters
    ----------
    mcp : FastMCP
        Shared FastMCP app created in mcp_server.server.
    """

    @mcp.tool()
    async def search_incident_memory(
        context_query: str,
        thread_id: str = "",
        include_cross_thread: bool = True,
        limit: int = 5,
        incident_type: str = "",
    ) -> dict[str, Any]:
        """Search incident memory using context-query embedding + Qdrant similarity.

        This tool supports historical-retrieval questions such as:
        - "Has this happened before?"
        - "What did we do last time?"

        Parameters
        ----------
        context_query : str
            Natural-language incident description.
        thread_id : str
            Current conversation thread id. Optional when include_cross_thread=True.
        include_cross_thread : bool
            True to search organization-wide incident memory, False for same-thread only.
        limit : int
            Maximum number of incident matches to return.
        incident_type : str
            Optional exact incident_type filter (e.g. SALES_DROP).

        Returns
        -------
        dict
            Context query metadata and ranked incident matches with similarity score.
        """
        log.info(
            "📞 [MEMORY] search_incident_memory called | context_query=%s | thread_id=%s | include_cross_thread=%s | limit=%s | incident_type=%s",
            context_query[:80],
            thread_id,
            include_cross_thread,
            limit,
            incident_type,
        )
        from app.services.agent_memory import retrieve_incident_memories

        return await retrieve_incident_memories(
            context_query=context_query,
            thread_id=thread_id or None,
            include_cross_thread=include_cross_thread,
            limit=max(1, min(limit, 20)),
            incident_type=incident_type or None,
        )

    @mcp.tool()
    async def get_action_effectiveness_summary(
        incident_type: str = "",
        limit: int = 8,
    ) -> dict[str, Any]:
        """Return ranked historical action effectiveness metrics.

        Aggregates incident outcomes and computes success rates for previously
        executed actions, enabling agents to choose actions with stronger
        historical evidence.

        Parameters
        ----------
        incident_type : str
            Optional exact incident_type filter.
        limit : int
            Number of top actions to return.

        Returns
        -------
        dict
            Ranked action rows with count, success_rate, outcome distribution,
            and confidence score.
        """
        log.info(
            "📞 [MEMORY] get_action_effectiveness_summary called | incident_type=%s | limit=%s",
            incident_type,
            limit,
        )
        from app.services.agent_memory import get_action_effectiveness_overview

        return await get_action_effectiveness_overview(
            incident_type=incident_type or None,
            limit=max(1, min(limit, 20)),
        )
