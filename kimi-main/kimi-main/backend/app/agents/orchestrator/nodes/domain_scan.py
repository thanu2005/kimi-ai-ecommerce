"""Phase 1 — Parallel domain scan node."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.agents.state import OrchestratorState, SubAgentState
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


async def _run_domain_agent(
    agent_cls,
    domain_key: str,
    sub_state: SubAgentState,
) -> dict[str, Any]:
    """Instantiate a domain agent, run it, return whiteboard update."""
    try:
        agent = agent_cls()
        result = await agent.run(sub_state)
        discoveries = result.get("discoveries", [])
        proposed = result.get("proposed_actions", [])
        log.info("[%s] Completed — %d finding(s), %d action(s) proposed",
                 domain_key.upper(), len(discoveries), len(proposed))
    except asyncio.TimeoutError:
        log.error("[%s] TIMED OUT — skipping domain", domain_key.upper())
        discoveries = [f"ERROR: {domain_key} agent timed out"]
        proposed = []
    except Exception as exc:
        log.error("[%s] FAILED: %s", domain_key.upper(), exc)
        discoveries = [f"ERROR: {domain_key} agent failed — {exc!s}"]
        proposed = []

    return {
        "domain": domain_key,
        "findings": discoveries,
        "proposed_actions": proposed,
    }


async def parallel_domain_scan_node(state: OrchestratorState) -> dict[str, Any]:
    """Pure executor — runs the agents planned by supervisor_node.

    Reads ``retry_domains`` (feedback run) or ``selected_agents`` (first run)
    from state alongside ``agent_goals``.  No planning logic lives here —
    that is entirely the responsibility of ``supervisor_node``.
    """
    retry_domains: list[str] = state.get("retry_domains") or []
    agent_goals: dict[str, str] = state.get("agent_goals") or {}
    iteration: int = state.get("iteration", 1)

    if retry_domains:
        domains_to_run = retry_domains
        log.info("=== PHASE 1: Targeted re-scan (iteration %d) — domains: %s ===",
                 iteration, ", ".join(domains_to_run))
    else:
        domains_to_run = state.get("selected_agents") or []
        log.info("=== PHASE 1: Parallel domain scan — domains: %s ===", ", ".join(domains_to_run))

    agents_to_run = [(v, d) for d in domains_to_run if (v := _ALL_AGENTS_MAP.get(d))]

    if not agents_to_run:
        log.warning("=== PHASE 1: No agents to run — check supervisor_node output ===")
        return {}

    query_type: str = state.get("query_type") or "REPORT"

    t0 = time.perf_counter()
    base_sub_state: SubAgentState = {
        "messages": state["messages"],
        "query": state["query"],
        "memory_context": state.get("memory_context", ""),
        "incident_memory_context": state.get("incident_memory_context", {}),
        "action_effectiveness_context": state.get("action_effectiveness_context", ""),
        "agent_goal": "",
        "discoveries": [],
        "proposed_actions": [],
        "query_type": query_type,
    }

    tasks = [
        _run_domain_agent(agent_cls, domain_key,
                          {**base_sub_state, "agent_goal": agent_goals.get(domain_key, "")})
        for agent_cls, domain_key in agents_to_run
    ]

    results = await asyncio.gather(*tasks, return_exceptions=False)

    whiteboard: dict[str, Any] = dict(state.get("whiteboard") or {})
    all_proposed: list[dict] = list(state.get("proposed_actions") or [])

    for r in results:
        whiteboard[r["domain"]] = {
            "findings": r["findings"],
            "draft_actions": r["proposed_actions"],
        }
        all_proposed.extend(r["proposed_actions"])

    # Gate: REPORT and DIAGNOSTIC queries must never populate proposed_actions.
    # This prevents internal data-retrieval plans from being mistaken for
    # corrective actions and triggering a false HITL checkpoint.
    if query_type != "ACTION" and all_proposed:
        log.warning(
            "=== PHASE 1: Suppressing %d proposed action(s) — query_type=%s "
            "(only ACTION queries may trigger HITL) ===",
            len(all_proposed), query_type,
        )
        all_proposed = []

    log.info("=== PHASE 1 COMPLETE — %.1fs | %d total action(s) proposed ===",
             time.perf_counter() - t0, len(all_proposed))
    return {
        "whiteboard": whiteboard,
        "proposed_actions": all_proposed,
        "retry_domains": [],
    }
