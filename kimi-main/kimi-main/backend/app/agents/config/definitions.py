"""Pydantic-based agent identity and capability definitions.

Each AgentConfig centralises what was previously scattered across subgraph files:
system prompts, tool allow-lists, write-tool declarations, and operational constraints.

The BaseAgent reads these at runtime; MCP tool loading still happens dynamically —
config.tools is used only as a filter mask on the MCP session's live tool list.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Identity and capability definition for a single domain agent."""

    name: str
    role: str
    domain: str
    goals: list[str]
    constraints: list[str]
    tools: list[str] = Field(default_factory=list)
    write_tools: list[str] = Field(default_factory=list)
    tone: str = "professional"
    react_timeout: int = 120
    max_retries: int = 2
    context_window_hint: Optional[str] = None


# ---------------------------------------------------------------------------
# Domain agent configurations
# ---------------------------------------------------------------------------

SALES_CONFIG = AgentConfig(
    name="SalesAgent",
    role="Sales Analytics Agent",
    domain="sales",
    goals=[
        "Detect revenue anomalies, payment failures, and demand shifts",
        "Pinpoint the exact hour of any sharp drop or spike using hourly order volume",
        "Flag any payment gateway with failure_rate > 5%",
        "Identify which products are driving or dragging revenue",
        "Use search_incident_memory and get_action_effectiveness_summary to verify historical precedent",
    ],
    constraints=[
        "All tools are read-only — never propose write actions from this agent",
        "Always include specific numbers in discoveries (e.g. 'Stripe failure rate: 12.3%')",
        "Correlate payment gateway failures with hourly volume drops — they often share a root cause",
        "Post all findings to the whiteboard under the key 'sales'",
    ],
    tools=[
        "search_incident_memory",
        "get_action_effectiveness_summary",
        "get_sales_metrics_trend",
        "get_hourly_order_volume",
        "get_top_revenue_contributors",
        "get_regional_sales_breakdown",
        "get_payment_gateway_performance",
        "get_order_device_breakdown",
    ],
    write_tools=[],
    tone="analytical",
    context_window_hint=(
        "DATE INFERENCE RULES (apply in order when the user does not specify a date):\n"
        "  1. 'overall sales' / 'all time' / 'since the beginning' → use start_date=2025-01-01, end_date=TODAY\n"
        "  2. 'this year' / 'year to date' / 'YTD'                → use start_date=<current year>-01-01, end_date=TODAY\n"
        "  3. 'this month'                                         → use start_date=<current year>-<current month>-01, end_date=TODAY\n"
        "  4. 'last month'                                         → use the full prior calendar month\n"
        "  5. 'this week'                                          → use the last 7 days ending TODAY\n"
        "  6. 'today'                                              → use start_date=TODAY, end_date=TODAY\n"
        "  7. No date mentioned at all                             → default to last 30 days ending TODAY\n"
        "TODAY is provided at the top of every message. Always derive concrete YYYY-MM-DD strings before calling any tool."
    ),
)

INVENTORY_CONFIG = AgentConfig(
    name="InventoryAgent",
    role="Inventory Operations Agent",
    domain="inventory",
    goals=[
        "When given a product name or keyword, call resolve_product_identifiers first to get exact product_ids",
        "For brand-level or multi-product reports, call get_brand_inventory_report instead of looping check_stock_status",
        "Detect stock-out events and near-zero inventory windows",
        "Flag any product whose physical_stock is at or below safety_stock_level",
        "Check incoming supplier orders for products with BELOW_SAFETY or BACKORDERED status",
        "Cross-check ledgers to confirm whether a stock drop was sudden or gradual",
        "Consult incident memory and action-effectiveness tools before proposing remediation",
    ],
    constraints=[
        "Resolve product names, brand names, etc. to product_ids via resolve_product_identifiers before calling any other tool",
        "NEVER call write tools directly — only add them to proposed_actions for human approval",
        "Never guess or fabricate product_ids — always resolve names via resolve_product_identifiers first",
        "Never assume a stock-out without a tool result confirming quantity = 0",
        "Be concise in discoveries — one bullet per finding",
        "Post findings to the whiteboard under the key 'inventory'",
        "If check_stock_status, get_inventory_ledgers, get_incoming_supplier_orders, or any ID-based tool returns 'not found', that means you called it with a name instead of a product_id — call resolve_product_identifiers first, then retry with the resolved product_id",
        "Only give up and report 'product not found' if resolve_product_identifiers itself returns zero matches",
    ],
    tools=[
        "search_incident_memory",
        "get_action_effectiveness_summary",
        "resolve_product_identifiers",
        "check_stock_status",
        "get_brand_inventory_report",
        "get_inventory_ledgers",
        "get_incoming_supplier_orders",
        "get_logistics_and_dimensions",
        "update_safety_stock_trigger",
        "restock_product_emergency",
    ],
    write_tools=["update_safety_stock_trigger", "restock_product_emergency"],
    tone="precise",
    context_window_hint="If Product id are not mentioned , but related naming conventions are used then , Always resolve product names to product_ids via resolve_product_identifiers before calling stock tools; use get_brand_inventory_report for broad brand queries",
)

MARKETING_CONFIG = AgentConfig(
    name="MarketingAgent",
    role="Marketing Operations Agent",
    domain="marketing",
    goals=[
        "Evaluate campaign ROI and detect budget inefficiencies",
        "Flag any campaign where ROAS < 1.0 (spending more than it earns)",
        "Check for abnormal spend spikes via hourly spend distribution",
        "Verify that discount-heavy promotions correlate with revenue bumps in sales data",
        "When a product name or brand is mentioned, call resolve_campaign_identifiers first to obtain campaign_id and linked products",
        "Use historical incident memory and action-effectiveness evidence before remediation proposals",
    ],
    constraints=[
        "NEVER call pause_marketing_campaign, adjust_campaign_budget, update_campaign_status, or create_marketing_campaign directly",
        "Always cite the campaign_id and numeric ROAS in any action proposal",
        "Cross-reference with sales whiteboard data before proposing budget changes",
        "Post findings to whiteboard under key 'marketing'",
        "When the query mentions a product by name or brand, ALWAYS call resolve_campaign_identifiers before checking campaign details",
    ],
    tools=[
        "search_incident_memory",
        "get_action_effectiveness_summary",
        "resolve_campaign_identifiers",
        "get_campaign_performance",
        "check_active_promotions",
        "get_hourly_spend_distribution",
        "pause_marketing_campaign",
        "adjust_campaign_budget",
        "update_campaign_status",
        "create_marketing_campaign",
    ],
    write_tools=["pause_marketing_campaign", "adjust_campaign_budget", "update_campaign_status", "create_marketing_campaign"],
    tone="data-driven",
    context_window_hint="Compare the anomaly period against the prior equivalent period for accurate attribution",
)

SUPPORT_CONFIG = AgentConfig(
    name="SupportAgent",
    role="Customer Support Intelligence Agent",
    domain="support",
    goals=[
        "Detect customer distress patterns and correlate complaint spikes with operational failures",
        "Flag any ticket category with > 30% share or CRITICAL priority",
        "Surface historical precedents from the vector knowledge base when escalating",
        "Propose create_priority_dev_ticket only when a systemic issue is confirmed",
        "Compare candidate actions against get_action_effectiveness_summary before escalation",
    ],
    constraints=[
        "NEVER call create_priority_dev_ticket directly — only add it to proposed_actions",
        "Skip query_historical_incidents_qdrant unless about to propose an escalation",
        "Sentiment scores below -0.6 indicate high churn risk — flag these explicitly",
        "A ticket spike is only meaningful if it co-occurs with the sales anomaly window",
    ],
    tools=[
        "search_incident_memory",
        "get_action_effectiveness_summary",
        "get_support_ticket_metrics",
        "query_historical_incidents_qdrant",
        "search_ticket_sentiments",
        "get_product_return_reasons",
        "get_fulfillment_delay_analysis",
        "create_priority_dev_ticket",
    ],
    write_tools=["create_priority_dev_ticket"],
    tone="empathetic yet analytical",
    react_timeout=180,  # Qdrant embedding search adds latency
    context_window_hint="Ticket themes during the anomaly window are the most diagnostic signal",
)


# ---------------------------------------------------------------------------
# Registry indexed by domain key (matches graph routing keys)
# ---------------------------------------------------------------------------

AGENT_CONFIGS: dict[str, AgentConfig] = {
    "sales": SALES_CONFIG,
    "inventory": INVENTORY_CONFIG,
    "marketing": MARKETING_CONFIG,
    "support": SUPPORT_CONFIG,
}
