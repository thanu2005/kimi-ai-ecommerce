"""Builds the system prompt string from an AgentConfig.

Keeps prompt logic out of agent class bodies so configs stay declarative
and prompt structure changes are made in one place.
"""

from __future__ import annotations

from app.agents.config.definitions import AgentConfig

_PRODUCT_ID_ENTRY_GATE = """
===== MANDATORY FIRST-STEP DECISION GATE =====
Before calling ANY other tool, you MUST inspect the user query:

STEP 1 — Does the query mention a product by NAME, TITLE, or BRAND
         (e.g., "ProSound Wireless Headphones", "leather jacket", "Nike shoes")?

  YES → Your FIRST tool call must be EXACTLY:
          Tool name : resolve_product_identifiers
          Argument  : name_or_keyword = "<the product name from the query>"

        Example call: resolve_product_identifiers(name_or_keyword="Nike Air zoom runner")

        Then use the product_id values returned from that tool for all subsequent calls.
        DO NOT call check_stock_status, get_inventory_ledgers, get_incoming_supplier_orders,
        update_safety_stock_trigger, restock_product_emergency, or any other tool
        until you have a confirmed product_id from resolve_product_identifiers.

  NO  → The query already contains explicit product_id strings (format: PROD-XX-NNN).
        Proceed directly to the appropriate read tool.

CRITICAL RULES:
- NEVER pass name_or_keyword to any tool other than resolve_product_identifiers.
- NEVER call restock_product_emergency or update_safety_stock_trigger during analysis
  — these are write tools that require human approval and must only go into proposed_actions.
- If resolve_product_identifiers returns zero matches, report the product was not found
  in the catalog and stop immediately. Do not retry with the same or similar name.
- NEVER fabricate, guess, or infer a product_id string.
==============================================
"""


def build_system_prompt(config: AgentConfig) -> str:
    """Render a full system prompt string from an AgentConfig.

    The prompt structure:
    0. Entry gate   — mandatory first-step decision tree (injected for agents
                      that have resolve_product_identifiers in their tool list)
    1. Role header  — who the agent is
    2. Goals        — what to investigate (numbered)
    3. Constraints  — hard rules the agent must follow (bulleted)
    4. Tone note    — communication style
    5. Context hint — time-window or focus guidance (optional)

    The output-format / write-tool action-proposal suffix is NOT included
    here — that is injected by BaseAgent._build_actions_suffix() at runtime
    so it can be dynamically adapted to query_type (REPORT vs ACTION).
    """
    lines: list[str] = []

    # Entry gate — injected only for agents that have the resolver tool
    if "resolve_product_identifiers" in config.tools or "resolve_campaign_identifiers" in config.tools:
        lines.append(_PRODUCT_ID_ENTRY_GATE.strip())
        lines.append("")

    # Role header
    lines.append(f"You are the {config.role} for an e-commerce platform.")
    lines.append("")

    # Goals
    lines.append("YOUR GOALS FOR THIS RUN:")
    for i, goal in enumerate(config.goals, start=1):
        lines.append(f"{i}. {goal}")
    lines.append("")

    # Constraints
    lines.append("RULES YOU MUST FOLLOW:")
    for constraint in config.constraints:
        lines.append(f"- {constraint}")
    lines.append("")

    # Tone
    lines.append(f"Communication tone: {config.tone}.")

    # Context hint
    if config.context_window_hint:
        lines.append("")
        lines.append(f"FOCUS GUIDANCE: {config.context_window_hint}")

    return "\n".join(lines)
