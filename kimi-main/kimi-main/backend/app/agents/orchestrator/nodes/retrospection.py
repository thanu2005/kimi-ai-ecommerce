"""Phase 1.5 — Collaborative retrospection node."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.agents.state import OrchestratorState
from app.agents.subgraphs.inventory_graph import InventoryAgent
from app.agents.subgraphs.marketing_graph import MarketingAgent
from app.agents.subgraphs.sales_graph import SalesAgent
from app.agents.subgraphs.support_graph import SupportAgent

log = logging.getLogger(__name__)

_ALL_AGENTS_MAP: dict[str, Any] = {
    "inventory": InventoryAgent,
    "sales": SalesAgent,
    "marketing": MarketingAgent,
    "support": SupportAgent,
}


async def _run_retrospection(
    agent_cls,
    domain_key: str,
    whiteboard: dict[str, Any],
    query: str,
    agent_goal: str = "",
    query_type: str = "ACTION",
) -> dict[str, Any]:
    """Instantiate an agent and run its retrospection pass."""
    try:
        agent = agent_cls()
        prior = whiteboard.get(domain_key, {})
        result = await agent.retrospect(
            domain=domain_key,
            prior_findings=prior.get("findings", []),
            prior_actions=prior.get("draft_actions", []),
            peer_whiteboard=whiteboard,
            query=query,
            agent_goal=agent_goal,
            query_type=query_type,
        )
        log.info("[%s][RETROSPECT] %d revised finding(s), %d revised action(s)",
                 domain_key.upper(),
                 len(result.get("discoveries", [])),
                 len(result.get("proposed_actions", [])))
        return {"domain": domain_key, **result}
    except Exception as exc:
        log.error("[%s][RETROSPECT] Failed: %s — keeping Phase 1 results", domain_key.upper(), exc)
        prior = whiteboard.get(domain_key, {})
        return {
            "domain": domain_key,
            "discoveries": prior.get("findings", []),
            "proposed_actions": prior.get("draft_actions", []),
        }


async def collaborative_retrospection_node(state: OrchestratorState) -> dict[str, Any]:
    """Phase 1.5 — Agents read peers' findings and revise their own.

    Each agent that ran in Phase 1 is given its own draft findings + all other
    agents' findings from the whiteboard.  It may call its read tools again to
    verify cross-domain hypotheses, then returns revised findings and updated
    proposed_actions.

    All retrospections run in parallel (same fan-out pattern as Phase 1).
    Skipped on feedback-loop iterations (iteration > 1) because peer findings
    are unchanged — only the rejected domain re-runs.
    """
    log.info("=== PHASE 1.5: Collaborative Retrospection ===")
    t0 = time.perf_counter()

    if (state.get("iteration") or 1) > 1:
        log.info("=== PHASE 1.5 SKIPPED — feedback iteration %d, peers unchanged ===",
                 state.get("iteration", 1))
        return {}

    whiteboard: dict[str, Any] = dict(state.get("whiteboard") or {})
    query = state.get("query", "")
    selected = state.get("selected_agents", [])
    agent_goals: dict[str, str] = state.get("agent_goals") or {}
    query_type: str = state.get("query_type") or "ACTION"

    tasks = [
        _run_retrospection(
            _ALL_AGENTS_MAP[domain], domain, whiteboard, query,
            agent_goals.get(domain, ""), query_type,
        )
        for domain in selected
        if domain in _ALL_AGENTS_MAP and domain in whiteboard
    ]

    if not tasks:
        log.info("=== PHASE 1.5 SKIPPED — no agents to retrospect ===")
        return {}

    results = await asyncio.gather(*tasks, return_exceptions=False)

    revised_whiteboard = dict(whiteboard)
    revised_proposed: list[dict] = []
    for r in results:
        domain = r["domain"]
        revised_whiteboard[domain] = {
            "findings": r.get("discoveries", []),
            "draft_actions": whiteboard.get(domain, {}).get("draft_actions", []),
            "revised": True,
        }
        revised_proposed.extend(r.get("proposed_actions", []))

    # Gate: REPORT and DIAGNOSTIC queries must never surface proposed_actions,
    # even if an agent's retro pass produced them (hallucination or prompt leak).
    if query_type != "ACTION" and revised_proposed:
        log.warning(
            "=== PHASE 1.5: Suppressing %d proposed action(s) — query_type=%s ===",
            len(revised_proposed), query_type,
        )
        revised_proposed = []

    log.info("=== PHASE 1.5 COMPLETE — %.1fs | query_type=%s | %d revised action(s) ===",
             time.perf_counter() - t0, query_type, len(revised_proposed))
    return {"whiteboard": revised_whiteboard, "proposed_actions": revised_proposed}
