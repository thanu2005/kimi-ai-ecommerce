"""Intent extraction node — classify query intent and select relevant domains."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.orchestrator.llm import build_llm
from app.agents.subgraphs.inventory_graph import InventoryAgent
from app.agents.subgraphs.marketing_graph import MarketingAgent
from app.agents.subgraphs.sales_graph import SalesAgent
from app.agents.subgraphs.support_graph import SupportAgent

log = logging.getLogger(__name__)

_ALL_AGENTS: dict[str, tuple] = {
    "inventory": (InventoryAgent, "inventory"),
    "sales": (SalesAgent, "sales"),
    "marketing": (MarketingAgent, "marketing"),
    "support": (SupportAgent, "support"),
}

_VALID_QUERY_TYPES = {"REPORT", "DIAGNOSTIC", "ACTION"}

# Appended to every domain goal when the query is read-only (REPORT or DIAGNOSTIC).
# Critical: must NOT discourage tool calls — only constrains proposed_actions output.
_READ_ONLY_GOAL_SUFFIX = (
    " — This is a {qtype} query: call all your read tools normally to gather real data. "
    "After collecting findings, output an empty proposed_actions array []."
)


async def extract_intent_and_agents(
    query: str,
    conversation_history: str = "",
) -> tuple[list[tuple], dict[str, str], str, bool, bool, bool]:
    """Classify query intent and extract relevant domains with per-domain goals.

    Returns
    -------
    agents_to_run : list[tuple]
        ``(AgentClass, domain_key)`` pairs for the parallel domain scan.
    goals : dict[str, str]
        Per-domain one-sentence directives (with read-only enforcement suffix
        already embedded for REPORT / DIAGNOSTIC queries).
    query_type : str
        One of ``"REPORT"``, ``"DIAGNOSTIC"``, or ``"ACTION"``.
    requires_remediation : bool
        ``True`` only for ACTION queries — permits subgraphs to append
        capital-committing entries to ``proposed_actions``.
    needs_incident_memory : bool
        ``True`` when the query should load historical incident matches prior
        to domain scans.
    needs_action_effectiveness : bool
        ``True`` when the query explicitly asks whether past actions worked,
        improved outcomes, or should be compared for effectiveness.
    """
    try:
        llm = build_llm()

        history_section = ""
        if conversation_history.strip():
            history_section = (
                "PRIOR CONVERSATION CONTEXT:\n"
                f"{conversation_history}\n\n"
                "ENTITY EXTRACTION (do this before writing goals):\n"
                "- Identify all product names, product_ids (format PROD-XX-NNN), brands mentioned in prior turns\n"
                "- Identify all date ranges, years, or quarters mentioned in prior turns\n"
                "- The current query may be a follow-up that references these implicitly (e.g. 'compare those products', 'use 2025')\n"
                "- When writing domain goals, embed the extracted product names/IDs and date ranges explicitly\n\n"
            )

        extraction_prompt = f"""{history_section}You are an expert business operations analyst. Analyze the query below in two steps: first classify its intent, then select the relevant business domains.

QUERY:
{query}

IMPORTANT: If this is a follow-up question, use the prior conversation context to understand what entity (product ID, date range, etc.) is being referred to.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — INTENT CLASSIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Classify the query into exactly one of three types:

1. "REPORT" — Exploratory / Analytical intent
   Examples: "Give me the sales report of 2025", "Summarize yesterday's business health", "Show revenue trends by channel"
   → query_type = "REPORT", requires_remediation = false
   → Downstream agents MUST write all findings into domain_findings. The proposed_actions array MUST remain completely empty ([]). Sequential database reads or month-by-month query plans are internal execution steps — they are NEVER actions and must NEVER enter proposed_actions.

2. "DIAGNOSTIC" — Root-cause analysis intent
   Examples: "Why did sales drop yesterday?", "Correlate complaints with the revenue dip", "What caused the inventory shortfall?"
   → query_type = "DIAGNOSTIC", requires_remediation = false
   → Agents investigate and write findings to domain_findings. proposed_actions stays empty unless an explicit "fix it" instruction is also present in the same query.

3. "ACTION" — Remedial / State-mutation intent
   Examples: "Fix the problem", "Restock affected products", "Pause the worst-performing campaign", "Issue vouchers to affected customers"
   → query_type = "ACTION", requires_remediation = true
   → Agents may append capital-committing or state-mutating resolution objects to proposed_actions. These require human approval via the HITL checkpoint.

CRITICAL DISTINCTION — Data Retrieval Plans vs Corrective Actions:
• Data Retrieval Plans  (e.g. "check each month's revenue", "analyse inventory levels", "query sales by region") are INTERNAL execution steps — they MUST NEVER appear in proposed_actions regardless of query_type.
• Corrective Actions    (e.g. "restock SKU-123", "pause campaign C-99", "issue a refund") are state-mutating interventions — they go into proposed_actions ONLY for ACTION queries.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — DOMAIN SELECTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DOMAIN INCLUSION RULES:
- "inventory"  → stock, stockout, inventory, restock, safety stock, supplier, lead time, warehouse, physical stock, allocated stock
- "sales"      → revenue, GMV, orders, order volume, payment, gateway, device breakdown, hourly sales, transaction, checkout
- "marketing"  → campaign, ROAS, budget, spend, promotion, ad, conversion, email, social, performance
- "support"    → ticket, customer complaint, refund, return, feedback, satisfaction, sentiment, fulfillment delay, shipping
- Include ALL domains mentioned in the query, even if minor.
- Never include a domain not mentioned.
- If no specific domain is mentioned, include all 4.

GOAL WRITING RULES:
- Each goal is a single, specific, actionable sentence telling the agent exactly what to look for.
- If a product ID, date, or entity was mentioned in prior conversation, include it explicitly.
- Ground the goal in the original query's intent.
- For remediation-like queries, include a short instruction to validate historical precedent before suggesting actions.
- Do NOT embed read-only enforcement language in the goal — that is added automatically.

MEMORY FLAGS (set explicitly):
- needs_incident_memory = true only if historical incidents/precedents are needed for this query.
- needs_action_effectiveness = true only if the user asks about whether past actions worked/improved/effective.
- Do NOT infer these from keyword matching; decide from meaning + context.

Respond with ONLY a JSON object (no markdown, no explanation):

{{
  "query_type": "REPORT",
  "requires_remediation": false,
    "needs_incident_memory": false,
    "needs_action_effectiveness": false,
  "domains": [
    {{"name": "sales",     "goal": "<one focused sentence on what the sales agent should investigate>"}},
    {{"name": "inventory", "goal": "<one focused sentence on what the inventory agent should investigate>"}}
  ]
}}"""

        response = await llm.ainvoke([
            SystemMessage(content="You are an expert business operations analyst. Always respond with valid JSON only."),
            HumanMessage(content=extraction_prompt),
        ])

        response_text = response.content.strip()
        if "```" in response_text:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            response_text = response_text[start:end]

        parsed = json.loads(response_text)

        query_type: str = str(parsed.get("query_type", "REPORT")).upper()
        if query_type not in _VALID_QUERY_TYPES:
            log.warning("Unrecognised query_type '%s'; defaulting to REPORT", query_type)
            query_type = "REPORT"

        requires_remediation: bool = bool(parsed.get("requires_remediation", False))
        needs_incident_memory: bool = bool(parsed.get("needs_incident_memory", False))
        needs_action_effectiveness: bool = bool(parsed.get("needs_action_effectiveness", False))
        # Consistency guard: only ACTION queries may trigger remediation / HITL
        if query_type != "ACTION":
            requires_remediation = False

        domain_entries = parsed.get("domains", [])
        valid_entries = [e for e in domain_entries if e.get("name") in _ALL_AGENTS]
        if not valid_entries:
            log.warning("LLM returned no valid domains; defaulting to all 4")
            valid_entries = [{"name": d, "goal": ""} for d in _ALL_AGENTS]

        result = [_ALL_AGENTS[e["name"]] for e in valid_entries]

        # Embed the read-only enforcement suffix into every goal for non-ACTION queries
        # so each subgraph's ReAct prompt carries the constraint explicitly.
        suffix = _READ_ONLY_GOAL_SUFFIX.format(qtype=query_type) if query_type != "ACTION" else ""
        goals = {
            e["name"]: (e.get("goal", "") + suffix).strip()
            for e in valid_entries
        }

        log.info(
            "Intent extracted — query_type=%s, requires_remediation=%s, needs_incident_memory=%s, needs_action_effectiveness=%s, domains=[%s]",
            query_type,
            requires_remediation,
            needs_incident_memory,
            needs_action_effectiveness,
            ", ".join(d for _, d in result),
        )
        for domain, goal in goals.items():
            log.info("  [%s] goal: %s", domain.upper(), goal)

        return (
            result,
            goals,
            query_type,
            requires_remediation,
            needs_incident_memory,
            needs_action_effectiveness,
        )

    except Exception as exc:
        log.warning("Intent extraction failed (%s); defaulting to all 4 agents, REPORT type", exc)
        return list(_ALL_AGENTS.values()), {}, "REPORT", False, False, False
