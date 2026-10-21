"""Phase 3 — HITL execution node."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.state import OrchestratorState

log = logging.getLogger(__name__)


def _sanitize_tool_params(
    tool_name: str, tool: Any, params: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Filter action params to only those accepted by the target tool schema.

    Proposed actions come from LLM output and may include helpful-but-invalid
    fields inferred from docstrings. This guard keeps execution aligned with the
    actual MCP tool signature by dropping unknown kwargs before ``ainvoke``.
    """
    schema = getattr(tool, "args_schema", None)
    if schema is None and hasattr(tool, "get_input_schema"):
        try:
            schema = tool.get_input_schema()
        except Exception:
            schema = None

    if schema is None:
        return params, []

    allowed_fields: set[str] = set()
    if hasattr(schema, "model_fields"):
        allowed_fields = set(schema.model_fields.keys())
    elif hasattr(schema, "__fields__"):
        allowed_fields = set(schema.__fields__.keys())

    if not allowed_fields:
        return params, []

    sanitized = {k: v for k, v in params.items() if k in allowed_fields}
    dropped = [k for k in params if k not in allowed_fields]
    if dropped:
        log.warning("[EXECUTE] Tool '%s' dropping unsupported param(s): %s",
                    tool_name, ", ".join(sorted(dropped)))
    return sanitized, dropped


async def execute_approved_actions_node(state: OrchestratorState) -> dict[str, Any]:
    """Execute all staged actions: pending_execution (prior rounds) + proposed_actions (final approved).

    Merges ``pending_execution`` and ``proposed_actions`` into one list,
    connects to the MCP server, and calls each tool by name.
    Results (success or error) are collected and written back to the whiteboard.
    This node fires only when the human has approved all actions with no rejections.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    from app.agents.base import get_mcp_transport_config

    pending = state.get("pending_execution") or []
    final_approved = state.get("proposed_actions") or []
    all_actions = pending + final_approved

    if not all_actions:
        log.info("[EXECUTE] No actions to execute")
        return {
            "whiteboard": {
                **(state.get("whiteboard") or {}),
                "execution_result": "No actions to execute.",
            }
        }

    log.info("[EXECUTE] Connecting to MCP to run %d action(s) (%d pending + %d final)...",
             len(all_actions), len(pending), len(final_approved))

    transport_cfg = get_mcp_transport_config()
    client = MultiServerMCPClient({"ecommerce-ops": transport_cfg})
    all_tools = await client.get_tools()
    tool_map = {t.name: t for t in all_tools}

    results: list[dict] = []
    for action in all_actions:
        tool_name = action.get("action", "")
        params = action.get("params", {})
        reason = action.get("reason", "")

        if tool_name not in tool_map:
            log.error("[EXECUTE] Tool '%s' not found in MCP registry — skipping. Available: %s",
                      tool_name, sorted(tool_map.keys()))
            results.append({"action": tool_name, "status": "skipped",
                            "reason": "tool not found in MCP server"})
            continue

        try:
            tool = tool_map[tool_name]
            safe_params, dropped_params = _sanitize_tool_params(tool_name, tool, params)
            log.info("[EXECUTE] Calling %s with params=%s", tool_name, safe_params)
            raw = await tool.ainvoke(safe_params)
            output = (raw if isinstance(raw, (dict, list))
                      else json.loads(raw) if isinstance(raw, str) else str(raw))
            log.info("[EXECUTE] %s succeeded: %s", tool_name, output)
            entry = {"action": tool_name, "status": "success", "result": output, "reason": reason}
            if dropped_params:
                entry["dropped_params"] = dropped_params
            results.append(entry)
        except Exception as exc:
            log.error("[EXECUTE] %s FAILED: %s", tool_name, exc)
            results.append({"action": tool_name, "status": "error",
                            "error": str(exc), "reason": reason})

    success_count = sum(1 for r in results if r["status"] == "success")
    skip_count = sum(1 for r in results if r["status"] == "skipped")
    error_count = sum(1 for r in results if r["status"] == "error")
    log.info("[EXECUTE] Complete — %d succeeded, %d skipped, %d errors",
             success_count, skip_count, error_count)

    return {
        "proposed_actions": [],
        "pending_execution": [],
        "whiteboard": {
            **(state.get("whiteboard") or {}),
            "execution_result": {
                "total": len(all_actions),
                "success": success_count,
                "skipped": skip_count,
                "errors": error_count,
                "details": results,
            },
        }
    }
