"""Phase 3 — Response Formatter node.

Runs after execute_approved_actions_node (or after synthesizer when there are no
actions) and converts the raw synthesizer final_report + execution results into a
clean, query-focused narrative for the operator UI.

Key responsibilities
--------------------
- Strip internal tool-call param summaries from the rendered text.
- Keep cross-domain correlations, executive summary, and key findings.
- Re-frame the entire response around the original user query.
- Produce a single, coherent markdown response ready for direct rendering.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.orchestrator.llm import build_llm
from app.agents.state import OrchestratorState

log = logging.getLogger(__name__)

_SYSTEM = """\
You are a concise, operator-facing business analyst AI.
Your job is to turn a verbose internal analysis report into a clean, well-structured
response that directly addresses the operator's original query.

FORMATTING RULES:
1. Start with a direct answer to the query in 1–3 sentences (no heading needed).
2. Follow with a "## Key Findings" section — bullet points only, cross-domain, each ≤ 2 lines.
3. If there are cross-domain patterns worth highlighting, add "## Insights" (≤ 4 bullets).
4. ONLY include "## Actions Taken" if an EXECUTION RESULTS section is explicitly provided in the
   input below. If no EXECUTION RESULTS section appears, NEVER write an "## Actions Taken"
   section — not even if the analysis report mentions recommended or proposed actions.
5. Close with "## Risk Snapshot" — 2 bullets: immediate risk if nothing changes, long-term risk.
6. NEVER include: tool names, parameter listings, JSON snippets, param summaries, raw tool output.
7. NEVER add a section that is irrelevant to the user's query.
8. Use plain business language. Avoid jargon and internal system terminology.
9. Keep the total response under 400 words unless the query explicitly asks for depth.
10. No Emojis.
"""

_SYSTEM_REPORT = """\
You are a concise, operator-facing business analyst AI producing a structured REPORT response.
Your job is to produce BOTH a clean narrative AND a structured data block for interactive charts and tables.

NARRATIVE FORMATTING RULES:
1. Start with a direct answer to the query in 1–3 sentences (no heading needed).
2. Follow with a "## Key Findings" section — bullet points only, cross-domain, each ≤ 2 lines.
3. If there are notable cross-domain patterns, add "## Insights" (≤ 4 bullets).
4. Close with "## Risk Snapshot" — 2 bullets: immediate risk if nothing changes, long-term risk.
5. NEVER include: tool names, parameter listings, JSON snippets, raw tool output.
6. Use plain business language. Avoid jargon. No Emojis. Narrative under 350 words.

STRUCTURED DATA BLOCK:
Immediately after the narrative, append a data block using EXACTLY these markers on their own lines:
<!--REPORT_DATA-->
{json}
<!--/REPORT_DATA-->

The JSON must match this schema:
{
  "tables": [
    {
      "title": "string",
      "columns": ["Col 1", "Col 2"],
      "rows": [["cell", "cell"], ...]
    }
  ],
  "charts": [
    {
      "type": "bar" | "line" | "pie",
      "title": "string",
      "xKey": "x_field_name",
      "yKey": "y_field_name",
      "yLabel": "Y-axis label",
      "color": "#6366f1",
      "data": [{"<xKey>": "label", "<yKey>": numeric_value}, ...]
    }
  ]
}

MULTI-SERIES CHARTS (use when comparing 2+ products, channels, or categories on the same chart):
Instead of yKey (single series), use "series" — an array of series definitions:
{
  "type": "line" | "bar",
  "title": "string",
  "xKey": "x_field_name",
  "yLabel": "Y-axis label",
  "series": [
    {"key": "field_name_1", "label": "Human Label 1", "color": "#6366f1"},
    {"key": "field_name_2", "label": "Human Label 2", "color": "#22d3ee"}
  ],
  "data": [
    {"<xKey>": "January", "field_name_1": 120, "field_name_2": 30},
    ...
  ]
}

CRITICAL RULES:
- Only extract numbers EXPLICITLY stated in the analysis — never fabricate or estimate data.
- Chart data values MUST be raw numbers (e.g. 125000, not "$125,000" or "125,000").
- xKey / yKey (or series[].key) must exactly match the field names in the data objects.
- For time-series (daily/monthly trends) → prefer "line" type.
- For category comparisons → prefer "bar" type.
- For share / distribution data → prefer "pie" type.
- When comparing 2+ products/channels over time → use multi-series with the "series" array.
- Max 2 charts and 1 table unless the query explicitly covers multiple metrics.
- Always mention the timeline in the chart title.
- If no numerical data is present in the analysis, emit: {"tables": [], "charts": []}
"""


async def response_formatter_node(state: OrchestratorState) -> dict[str, Any]:
    """Format the synthesizer report into a clean operator-facing response.

    Reads ``whiteboard["final_report"]`` and any execution results, then uses
    the LLM to produce a focused, query-aware markdown narrative stored in
    ``whiteboard["formatted_response"]``.

    Parameters
    ----------
    state : OrchestratorState
        Current graph state after execute_approved_actions_node (or synthesizer
        when there are no actions to run).

    Returns
    -------
    dict
        Updated ``whiteboard`` with ``formatted_response`` key set.
    """
    log.info("=== RESPONSE FORMATTER: building operator-facing response ===")
    t0 = time.perf_counter()

    whiteboard: dict[str, Any] = state.get("whiteboard") or {}
    raw_report: str = whiteboard.get("final_report", "")
    query: str = state.get("query", "")
    query_type: str = state.get("query_type") or "REPORT"
    execution_result: Any = whiteboard.get("execution_result")

    execution_section = ""
    if execution_result:
        if isinstance(execution_result, list):
            lines = []
            for r in execution_result:
                action = r.get("action", "")
                outcome = r.get("result", r.get("output", "completed"))
                lines.append(f"- {action}: {outcome}")
            execution_section = "\n\nEXECUTION RESULTS:\n" + "\n".join(lines)
        else:
            execution_section = f"\n\nEXECUTION RESULTS:\n{execution_result}"

    if query_type == "REPORT":
        system = _SYSTEM_REPORT
        user_prompt = f"""ORIGINAL OPERATOR QUERY:
{query}

RAW INTERNAL ANALYSIS REPORT:
{raw_report}

Produce: (1) the clean operator-facing narrative following the formatting rules, then (2) the structured data block between the <!--REPORT_DATA--> markers.
Only include tables and charts where actual numbers are present in the analysis above."""
    else:
        system = _SYSTEM
        user_prompt = f"""ORIGINAL OPERATOR QUERY:
{query}

RAW INTERNAL ANALYSIS REPORT:
{raw_report}
{execution_section}

Now produce the clean, operator-facing response following all formatting rules.
Remember: never expose tool names, params, or internal system details."""

    try:
        llm = build_llm()
        response = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=user_prompt),
        ])
        formatted = response.content
        log.info("=== RESPONSE FORMATTER COMPLETE — %.1fs | query_type=%s ===",
                 time.perf_counter() - t0, query_type)
    except Exception as exc:
        log.error("=== RESPONSE FORMATTER FAILED: %s — falling back to raw report ===", exc)
        formatted = raw_report  # graceful fallback

    updated_whiteboard = dict(whiteboard)
    updated_whiteboard["formatted_response"] = formatted
    return {"whiteboard": updated_whiteboard}
