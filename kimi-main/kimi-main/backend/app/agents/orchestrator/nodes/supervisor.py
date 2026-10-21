"""Supervisor node — intent planning (run 1) and rejection refinement (feedback runs)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.orchestrator.llm import build_llm
from app.agents.orchestrator.nodes.intent_extraction import extract_intent_and_agents
from app.agents.state import OrchestratorState
from app.services.agent_memory import (
    build_action_effectiveness_context,
    get_action_effectiveness_overview,
    retrieve_incident_memories,
)

log = logging.getLogger(__name__)


async def supervisor_node(state: OrchestratorState) -> dict[str, Any]:
    """Single orchestrator node that handles both planning and rejection refinement.

    **First run (iteration == 1):**
        Calls ``extract_intent_and_agents`` to determine which domain agents
        are relevant and generates a focused one-sentence goal for each.
        Writes ``selected_agents``, ``agent_goals``, and ``retry_domains=[]``.

    **Feedback run (iteration > 1, rejected_actions present):**
        Reads ``rejected_actions`` + ``human_note``, uses the LLM to generate
        refined goals for the affected domains, stages the approved actions
        from this round into ``pending_execution``, and sets ``retry_domains``
        so Phase 1 runs only the re-queued agents.  Clears ``rejected_actions``
        so the HITL gateway does not re-trigger on the next pass.
    """
    iteration: int = state.get("iteration", 1)
    rejected: list[dict] = state.get("rejected_actions") or []

    # ------------------------------------------------------------------ #
    #  Path A — first run: intent extraction + goal generation            #
    # ------------------------------------------------------------------ #
    if iteration == 1 or not rejected:
        query = state.get("query", "")
        session_id = state.get("session_id")
        log.info("=== SUPERVISOR: intent extraction + agent goal generation (iteration %d) ===", iteration)

        # Build conversation history string from prior messages for context continuity.
        # Rather than dumping raw message text (which gets truncated and loses key entities),
        # we extract the full content of user turns and assistant summaries so the intent
        # extractor can pull out product names, product_ids, and date ranges explicitly.
        messages = state.get("messages") or []
        conversation_history = ""
        if len(messages) > 1:  # More than just the current query
            lines = []
            for msg in messages[:-1]:  # Exclude current query (last message)
                if hasattr(msg, "type"):
                    role = "User" if msg.type == "human" else "Assistant"
                else:
                    role = "User" if getattr(msg, "role", "user") == "user" else "Assistant"
                # Use up to 1000 chars per message to preserve product names and dates
                lines.append(f"{role}: {msg.content[:1000]}")
            conversation_history = "\n".join(lines[-10:])  # Last 5 turns (10 messages)

        (
            agents_to_run,
            agent_goals,
            query_type,
            requires_remediation,
            needs_incident_memory,
            needs_action_effectiveness,
        ) = await extract_intent_and_agents(
            query, conversation_history=conversation_history
        )

        incident_memory_context = state.get("incident_memory_context") or {
            "context_query": query,
            "include_cross_thread": True,
            "result_count": 0,
            "results": [],
        }
        if needs_incident_memory:
            try:
                incident_memory_context = await retrieve_incident_memories(
                    context_query=query,
                    thread_id=session_id,
                    include_cross_thread=True,
                    limit=5,
                )
            except Exception as exc:
                log.warning("[SUPERVISOR] incident memory retrieval failed: %s", exc)

        action_effectiveness_context = ""
        if needs_action_effectiveness:
            try:
                overview = await get_action_effectiveness_overview(limit=8)
                action_effectiveness_context = build_action_effectiveness_context(overview)
            except Exception as exc:
                log.warning("[SUPERVISOR] action-effectiveness context build failed: %s", exc)
        selected = [domain for _, domain in agents_to_run]
        log.info(
            "=== SUPERVISOR: query_type=%s, requires_remediation=%s, domains=[%s] ===",
            query_type, requires_remediation, ", ".join(selected),
        )
        return {
            "selected_agents": selected,
            "agent_goals": agent_goals,
            "query_type": query_type,
            "requires_remediation": requires_remediation,
            "needs_incident_memory": needs_incident_memory,
            "needs_action_effectiveness": needs_action_effectiveness,
            "incident_memory_context": incident_memory_context,
            "action_effectiveness_context": action_effectiveness_context,
            "retry_domains": [],
        }

    # ------------------------------------------------------------------ #
    #  Path B — feedback run: rejection refinement                        #
    # ------------------------------------------------------------------ #
    log.info("=== SUPERVISOR: rejection refinement (iteration %d) ===", iteration)
    t0 = time.perf_counter()
    llm = build_llm()

    approved_this_round: list[dict] = state.get("proposed_actions") or []
    human_note: str = state.get("human_note", "")
    existing_pending: list[dict] = state.get("pending_execution") or []
    query: str = state.get("query", "")
    whiteboard: dict = state.get("whiteboard") or {}

    new_pending = existing_pending + approved_this_round
    log.info("[SUPERVISOR] Staged %d approved action(s) → pending_execution (total=%d)",
             len(approved_this_round), len(new_pending))

    retry_domains = list({r.get("domain", "") for r in rejected if r.get("domain")})
    if not retry_domains:
        rejected_tools = {r.get("action", "") for r in rejected}
        for domain, data in whiteboard.items():
            if domain in ("final_report", "execution_result"):
                continue
            domain_tools = {a.get("action", "") for a in (data.get("draft_actions") or [])}
            if rejected_tools & domain_tools:
                retry_domains.append(domain)

    log.info("[SUPERVISOR] Retry domains: %s", retry_domains)

    rejection_lines = [
        f"- Action: {r.get('action', '?')}  |  Reason: {r.get('rejection_reason', 'no reason given')}"
        for r in rejected
    ]
    note_section = f"\nHuman additional note: {human_note}" if human_note else ""

    refinement_prompt = f"""The human operator rejected the following proposed actions. Generate refined agent goals.

ORIGINAL QUERY: {query}

REJECTED ACTIONS:
{chr(10).join(rejection_lines)}{note_section}

For each rejected domain, write a focused one-sentence goal that:
1. Acknowledges WHY the action was rejected.
2. Tells the agent what alternative direction to explore.
3. Is grounded in the rejection reason and human note.

Respond with ONLY a JSON object:
{{
  "refined_goals": [
    {{"domain": "<domain_name>", "goal": "<refined one-sentence goal>"}}
  ]
}}"""

    refined_goals: dict[str, str] = {}
    try:
        response = await llm.ainvoke([
            SystemMessage(content="You are a senior e-commerce operations orchestrator."),
            HumanMessage(content=refinement_prompt),
        ])
        response_text = response.content.strip()
        if "```json" in response_text:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            response_text = response_text[start:end]
        parsed = json.loads(response_text)
        for entry in parsed.get("refined_goals", []):
            refined_goals[entry["domain"]] = entry.get("goal", "")
            log.info("[SUPERVISOR] [%s] refined goal: %s", entry["domain"].upper(), entry.get("goal", ""))
    except Exception as exc:
        log.warning("[SUPERVISOR] LLM refinement failed (%s) — using rejection reason as fallback goal", exc)
        for r in rejected:
            domain = r.get("domain", "")
            if domain:
                refined_goals[domain] = r.get("rejection_reason", "Re-analyze and propose an alternative action.")

    updated_goals = dict(state.get("agent_goals") or {})
    updated_goals.update(refined_goals)

    log.info("=== SUPERVISOR: refinement complete — %.1fs | retry_domains=%s ===",
             time.perf_counter() - t0, retry_domains)

    return {
        "pending_execution": new_pending,
        "proposed_actions": [],
        "rejected_actions": [],
        "retry_domains": retry_domains,
        "agent_goals": updated_goals,
        "iteration": iteration + 1,
        "human_note": "",
    }
