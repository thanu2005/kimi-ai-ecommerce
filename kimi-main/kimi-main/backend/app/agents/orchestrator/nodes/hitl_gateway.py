"""HITL gateway node and its conditional route."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.state import OrchestratorState

log = logging.getLogger(__name__)


async def hitl_gateway_node(state: OrchestratorState) -> dict[str, Any]:
    """Lightweight interrupt target — routes after human submits approval decision.

    This node is the ``interrupt_before`` target.  When the graph resumes after
    the human submits their decision, this node runs and immediately returns
    empty state — all routing is handled by ``_route_from_hitl_gateway``.
    """
    return {}


def _route_from_hitl_gateway(state: OrchestratorState) -> str:
    """After HITL resume: rejected actions → supervisor refinement; else → execute.

    Safety guard: ``hitl_human_reviewed`` must be ``True`` before any execution
    is allowed.  This flag is only set by the /api/resume endpoint, ensuring
    the graph can never auto-execute if ``interrupt_before`` somehow does not
    fire (e.g., version mismatch or missing checkpointer).
    """
    if not state.get("hitl_human_reviewed"):
        log.error(
            "[HITL] SAFETY BLOCK — hitl_human_reviewed is False. "
            "Execution refused: human has not reviewed the proposed actions. "
            "Graph should have been paused at interrupt_before=[hitl_gateway]."
        )
        return "supervisor"

    rejected = state.get("rejected_actions") or []
    if rejected:
        log.info("[HITL] %d rejected action(s) — routing back to supervisor for refinement",
                 len(rejected))
        return "supervisor"
    log.info("[HITL] All actions approved — routing to execution")
    return "execute_approved_actions"
