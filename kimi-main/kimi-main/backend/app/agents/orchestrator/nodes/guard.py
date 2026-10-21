"""Guard node — fast relevance check that short-circuits the graph for
queries unrelated to e-commerce operations."""

from __future__ import annotations

import logging

from app.agents.orchestrator.llm import build_llm
from app.agents.state import OrchestratorState

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a relevance classifier for an e-commerce operations assistant.\n\n"
    "The assistant handles ONLY:\n"
    "  - Inventory (stock levels, reorders, suppliers, warehousing)\n"
    "  - Sales (revenue, orders, payment gateways, fulfilment)\n"
    "  - Marketing campaigns (ad spend, ROAS, channel performance)\n"
    "  - Customer support (tickets, refunds, defects, shipping delays)\n\n"
    "IMPORTANT: If prior conversation context is provided, the current query may be a "
    "follow-up that implicitly refers to e-commerce topics discussed earlier "
    "(e.g. 'compare those products', 'use 2025', 'show me the same for last year'). "
    "In that case, classify as YES even if the standalone query looks ambiguous.\n\n"
    "Reply with exactly one word — YES if the query relates to any of the above "
    "(directly or as a follow-up from context), NO otherwise. "
    "No punctuation, no explanation."
)

_REJECTION = (
    "I'm not designed for this purpose — please don't waste your tokens. "
    "Ask me about inventory, sales, marketing campaigns, or customer support operations."
)


async def guard_node(state: OrchestratorState) -> dict:
    """Return off_topic=True and a rejection message when the query is irrelevant."""
    query = state.get("query", "")

    # Build a compact history snippet so the guard can classify follow-up queries
    # correctly even when they don't mention domain keywords explicitly.
    messages = state.get("messages") or []
    history_snippet = ""
    if len(messages) > 1:
        lines = []
        for msg in messages[:-1]:
            if hasattr(msg, "type"):
                role = "User" if msg.type == "human" else "Assistant"
            else:
                role = "User" if getattr(msg, "role", "user") == "user" else "Assistant"
            lines.append(f"{role}: {msg.content[:300]}")
        if lines:
            history_snippet = "Prior conversation:\n" + "\n".join(lines[-6:]) + "\n\nCurrent query: "

    classified_input = history_snippet + query

    try:
        llm = build_llm()
        response = await llm.ainvoke([
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": classified_input},
        ])
        is_relevant = response.content.strip().upper().startswith("YES")
    except Exception:
        logger.exception("Guard node LLM call failed — defaulting to relevant")
        is_relevant = True

    if not is_relevant:
        return {
            "off_topic": True,
            "whiteboard": {"formatted_response": _REJECTION},
        }

    return {"off_topic": False}


def _route_from_guard(state: OrchestratorState) -> str:
    return "off_topic" if state.get("off_topic") else "supervisor"
