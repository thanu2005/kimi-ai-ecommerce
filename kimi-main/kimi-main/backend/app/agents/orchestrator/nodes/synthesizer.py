"""Phase 2 — Synthesizer node and its conditional route."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END

from app.agents.orchestrator.llm import build_llm
from app.agents.state import OrchestratorState

log = logging.getLogger(__name__)


async def synthesizer_node(state: OrchestratorState) -> dict[str, Any]:
    """Cross-domain analysis and final operational report in one LLM pass.

    Reads the post-retrospection whiteboard, identifies remaining cross-domain
    correlations, validates that retrospection resolved contradictions, ranks
    proposed actions by urgency and business impact, and compiles the final
    executive report — all in a single LLM call.
    """
    log.info("=== PHASE 2: Synthesizer — cross-domain analysis + final report ===")
    t0 = time.perf_counter()
    llm = build_llm()

    whiteboard = state.get("whiteboard") or {}
    proposed = state.get("proposed_actions") or []
    query_type: str = state.get("query_type") or "REPORT"

    whiteboard_text = "\n\n".join(
        f"=== {domain.upper()} {'[REVISED]' if data.get('revised') else ''} ===\n"
        + "\n".join(str(f) for f in data.get("findings", []))
        for domain, data in whiteboard.items()
        if domain not in ("final_report", "execution_result")
    )

    memory_ctx = state.get("memory_context", "")
    memory_section = f"\nHISTORICAL CONTEXT (from previous runs):\n{memory_ctx}" if memory_ctx else ""
    effectiveness_ctx = state.get("action_effectiveness_context", "")
    effectiveness_section = (
        f"\nACTION EFFECTIVENESS EVIDENCE:\n{effectiveness_ctx}"
        if effectiveness_ctx
        else ""
    )

    goals = state.get("orchestrator_goals", "")
    goals_section = f"\nOrchestrator directives for this cycle:\n{goals}" if goals else ""

    pending = state.get("pending_execution") or []
    iteration = state.get("iteration", 1)
    pending_section = (
        f"\nALREADY APPROVED (iteration {iteration - 1}, awaiting final execution):\n"
        + json.dumps(pending, indent=2)
    ) if pending else ""

    # Build action-related prompt sections conditionally.
    # The synthesizer NEVER generates new actions — it only ranks and annotates
    # whatever Phase 1 / Phase 1.5 agents already produced.
    if proposed:
        action_context = f"""
PROPOSED ACTIONS ({len(proposed)} total — produced by Phase 1 domain agents):
{json.dumps(proposed, indent=2)}
"""
        action_tasks = """5. RANKED ACTION PLAN — reorder the PROPOSED ACTIONS listed above by urgency and business impact. Do NOT invent new actions. Only rank and annotate the ones already listed above.
6. RISK ASSESSMENT — what happens if no action is taken.

IMPORTANT: For each item in the PROPOSED ACTIONS list above, add a "human_label" field — a single plain-English sentence describing WHAT the action will do (not the tool name, not params). Example: "Raise an emergency restock purchase order for 20 units of PROD-LJ-001".
Return the ranked, enriched actions as a JSON block at the very end:
```json
{{"proposed_actions_enriched": [
  {{"action": "<tool_name>", "reason": "<existing reason>", "params": {{}}, "human_label": "<plain English description>"}}
]}}
```"""
    else:
        action_context = ""
        action_tasks = "5. RISK ASSESSMENT — what happens if no corrective action is taken based on current findings."

    synthesis_prompt = f"""You are the senior operations strategist. The domain agents have completed their analysis and collaborative retrospection.

ORIGINAL QUERY: {state['query']}{memory_section}{effectiveness_section}{goals_section}{pending_section}

WHITEBOARD (post-retrospection — [REVISED] entries were updated after agents read each other's work):
{whiteboard_text}
{action_context}
Your task in a single structured response:
1. CROSS-DOMAIN CORRELATIONS — identify any correlations or patterns the agents may have missed across domains.
2. CONTRADICTION CHECK — flag any contradictions between domain findings that retrospection did not resolve.
3. HISTORICAL EVIDENCE PASS — compare this incident against prior similar incidents and explicitly state what worked or failed previously.
4. EXECUTIVE SUMMARY — 2-3 sentences summarising the overall operational situation.
5. KEY FINDINGS — bulleted, cross-domain.
{action_tasks}"""

    response = await llm.ainvoke([
        SystemMessage(content="You are a senior e-commerce operations strategist."),
        HumanMessage(content=synthesis_prompt),
    ])

    updated_whiteboard = dict(whiteboard)
    updated_whiteboard["final_report"] = response.content

    # Only attempt enrichment when Phase 1 produced actions.
    # If proposed was empty going in, enriched_proposed stays empty — the
    # synthesizer cannot introduce actions that did not exist upstream.
    import re as _re
    enriched_proposed = list(proposed)
    if proposed:
        match = _re.search(r"```json\s*(\{.*?\})\s*```", response.content, _re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                enriched = parsed.get("proposed_actions_enriched", [])
                if enriched:
                    enriched_proposed = enriched
                    log.info("=== SYNTHESIZER: enriched %d action(s) with human_label ===", len(enriched))
            except json.JSONDecodeError:
                log.warning("=== SYNTHESIZER: failed to parse enriched actions JSON ===")

    log.info("=== PHASE 2 COMPLETE — %.1fs | query_type=%s | %d action(s) passed downstream ===",
             time.perf_counter() - t0, query_type, len(enriched_proposed))
    return {"whiteboard": updated_whiteboard, "proposed_actions": enriched_proposed}


def _route_after_synthesis(state: OrchestratorState) -> str:
    """Route to HITL only for ACTION queries that produced upstream actions."""
    query_type: str = state.get("query_type") or "REPORT"

    # REPORT and DIAGNOSTIC queries never require human approval —
    # route directly to the response formatter regardless of proposed_actions.
    if query_type != "ACTION":
        log.info("[ROUTER] query_type=%s — bypassing HITL, routing to response_formatter",
                 query_type)
        return END

    actions = state.get("proposed_actions") or []
    pending = state.get("pending_execution") or []
    if actions or pending:
        log.info("[ROUTER] %d proposed + %d pending action(s) — routing to HITL gateway",
                 len(actions), len(pending))
        return "hitl_gateway"
    log.info("[ROUTER] No actions — zero-action auto-complete")
    return END
