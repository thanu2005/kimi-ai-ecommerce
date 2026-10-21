"""Abstract base class for all domain subgraph agents.

Architecture contract
---------------------
Every domain agent (Inventory, Sales, Marketing, Support) must subclass
``BaseAgent`` and implement ``build_graph()``.  The base class handles:

1. **MCP tool loading** — connects to ``mcp_server/server.py`` over stdio,
   loads only the tools declared in ``tool_names``, and converts them to
   LangChain-compatible ``StructuredTool`` objects via
   ``langchain_mcp_adapters``.

2. **LLM construction** — builds an ``AzureChatOpenAI`` instance wired to
   the DIAL gateway using settings from ``app.config``.

3. **ReAct agent creation** — wraps the LLM + filtered tools in a
   ``create_agent`` loop ready to be embedded in a LangGraph subgraph.

Tool isolation
--------------
Each subclass declares ``tool_names: list[str]`` — the *exact* subset of MCP
tool names it is allowed to call.  The base class filters the full MCP tool
list down to this subset before binding them to the LLM.  This keeps context
windows small and prevents agents from calling tools outside their domain.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import ToolNode

from app.agents.config.definitions import AgentConfig
from app.agents.config.prompt_builder import build_system_prompt
from app.agents.state import SubAgentState
from app.config import settings

log = logging.getLogger(__name__)

_MCP_SERVER_PATH = (
    Path(__file__).resolve().parents[3] / "mcp_server" / "server.py"
)


def get_mcp_transport_config() -> dict:
    """Return the MCP transport config for a MultiServerMCPClient.

    Prefers SSE when ``MCP_SSE_URL`` is configured (via .env or environment),
    connecting to the externally-started FastMCP SSE server.  Falls back to
    spawning a stdio subprocess if the URL is not set.

    To use SSE, start the server once in a terminal (from project root)::

        fastmcp run mcp_server/server.py:mcp --transport sse --port 8001

    then set ``MCP_SSE_URL=http://localhost:8001/sse`` in your ``.env``.
    """
    if settings.mcp_sse_url:
        return {"url": settings.mcp_sse_url, "transport": "sse"}
    return {
        "command": sys.executable,
        "args": [str(_MCP_SERVER_PATH)],
        "transport": "stdio",
    }


class _StringifyToolNode(ToolNode):
    """ToolNode that JSON-serialises dict tool outputs to strings.

    The DIAL API (and Claude-family models via Azure) require ToolMessage
    content to be a plain string.  MCP tools return dicts — this subclass
    converts them transparently so the LLM never sees a raw dict payload.
    """

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        result = await super().ainvoke(input, config, **kwargs)
        for msg in result.get("messages", []):
            if isinstance(msg, ToolMessage) and not isinstance(msg.content, str):
                msg.content = json.dumps(msg.content, default=str)
        return result


class BaseAgent(ABC):
    """Abstract base for all domain subgraph agents.

    Subclasses may either:
    - Set ``agent_config: AgentConfig`` (preferred) — tool_names, write_tool_names,
      and system_prompt are derived automatically from the config.
    - Or declare ``tool_names``, ``write_tool_names``, and ``system_prompt`` directly
      as class attributes (legacy, still supported).

    Call ``await agent.run(state)`` to execute.
    """

    # New config-based approach (preferred)
    agent_config: AgentConfig | None = None

    # Legacy class-attribute approach (used when agent_config is None)
    tool_names: list[str] = []
    system_prompt: str = "You are a helpful e-commerce operations agent."
    # Per-agent timeout in seconds (subclasses may override)
    react_timeout: int = 120
    # How many times to retry on timeout or transient error before giving up
    max_retries: int = 2

    def _get_tool_names(self) -> list[str]:
        """Return the agent's allowed MCP tool names."""
        if self.agent_config is not None:
            return self.agent_config.tools
        return self.tool_names

    def _get_write_tool_names(self) -> list[str]:
        """Return the agent's write-only tool names."""
        if self.agent_config is not None:
            return self.agent_config.write_tools
        write = getattr(self, "write_tool_names", None)
        if write is not None:
            return write
        read_prefixes = ("get_", "check_", "search_", "query_")
        return [n for n in self._get_tool_names() if not any(n.startswith(p) for p in read_prefixes)]

    def _get_system_prompt(self) -> str:
        """Return the rendered system prompt."""
        if self.agent_config is not None:
            return build_system_prompt(self.agent_config)
        return self.system_prompt

    def _get_react_timeout(self) -> int:
        if self.agent_config is not None:
            return self.agent_config.react_timeout
        return self.react_timeout

    def _get_max_retries(self) -> int:
        if self.agent_config is not None:
            return self.agent_config.max_retries
        return self.max_retries

    def _build_actions_suffix(self, write_tool_names: list[str], query_type: str = "ACTION") -> str:
        """Build the output-format instruction appended to the system prompt.

        For REPORT / DIAGNOSTIC queries the output block still requires a valid
        JSON structure but locks ``proposed_actions`` to an empty array, so the
        LLM cannot accidentally fill it with data-retrieval plans.  For ACTION
        queries the original write-tool allowlist behaviour is preserved.
        """
        if query_type != "ACTION":
            return f"""

---
OUTPUT FORMAT (mandatory — include at the very end of your FINAL response)
Call all your read tools as instructed above to gather real data.
This is a {query_type} query — do NOT propose write actions regardless of what you find.
Always append this exact block with an empty array:

```json
{{
  "proposed_actions": []
}}
```
---"""

        # ACTION query — original allowlist behaviour
        if write_tool_names:
            allowed = ", ".join(f'"{n}"' for n in write_tool_names)
            action_note = (
                f"ONLY propose actions using these exact tool names: {allowed}\n"
                "Any other action name will be rejected."
            )
        else:
            action_note = "This agent has no write tools — always use an empty proposed_actions array."
        return f"""

---
OUTPUT FORMAT (mandatory — include at the very end of your FINAL response)
After your analysis text, append a JSON block wrapped in ```json ... ``` markers.
{action_note}

The block must follow this exact schema:

```json
{{
  "proposed_actions": [
    {{
      "action": "<exact_tool_name_from_above>",
      "reason": "<one sentence rationale>",
      "params": {{"<param_name>": "<value>"}}
    }}
  ]
}}
```

HISTORICAL EVIDENCE PASS (mandatory for ACTION queries):
- Before finalizing proposed_actions, review provided historical context.
- If historical precedents exist, each action "reason" must reference that precedent succinctly
    (e.g., "historically improved in 4/6 similar incidents").
- Prefer actions with stronger historical success rates when multiple valid options exist.

Do NOT call write tools directly. Only list them in the JSON block above.
---"""

    def _build_llm(self) -> AzureChatOpenAI:
        """Construct the AzureChatOpenAI instance wired to the DIAL gateway."""
        return AzureChatOpenAI(
            azure_endpoint=settings.dial_endpoint,
            azure_deployment=settings.dial_chat_deployment,
            api_version=settings.dial_api_version,
            api_key=settings.dial_api_key,
            default_headers={"Api-Key": settings.dial_api_key},
            temperature=0,
            max_retries=3,
        )

    async def run(self, state: SubAgentState) -> dict[str, Any]:
        """Load MCP tools, build a ReAct agent, invoke it, return findings.

        Retries up to ``max_retries`` times on timeout or transient error
        with a short back-off between attempts.
        """
        from langchain_core.messages import HumanMessage
        from langchain_mcp_adapters.client import MultiServerMCPClient

        agent_name = self.__class__.__name__
        t0 = time.perf_counter()

        query = state.get("query", "Perform a full operational health check for today.")
        memory = state.get("memory_context", "")
        incident_memory = state.get("incident_memory_context", {})
        effectiveness_context = state.get("action_effectiveness_context", "")
        agent_goal = state.get("agent_goal", "")
        query_type: str = state.get("query_type") or "REPORT"

        # Inject the current date so the LLM never defaults to a stale training
        # date when the user query does not specify a time window explicitly.
        from datetime import date as _date
        today_str = _date.today().isoformat()
        date_header = (
            f"TODAY'S DATE: {today_str}\n"
            "Use this as the reference date for ALL tool calls unless the user "
            "explicitly specifies a different date or range.\n\n"
        )

        goal_section = f"\n\nYOUR SPECIFIC GOAL FOR THIS RUN:\n{agent_goal}" if agent_goal else ""
        memory_section = f"\n\nHistorical context:\n{memory}" if memory else ""
        incident_hits = incident_memory.get("results", []) if isinstance(incident_memory, dict) else []
        incident_lines = []
        for idx, hit in enumerate(incident_hits[:3], start=1):
            incident_lines.append(
                f"[{idx}] score={hit.get('score')} type={hit.get('incident_type')} "
                f"outcome={hit.get('outcome_label')} run_id={hit.get('run_id')}"
            )
        incident_section = (
            "\n\nCross-thread incident matches:\n" + "\n".join(incident_lines)
            if incident_lines
            else ""
        )
        effectiveness_section = (
            f"\n\n{effectiveness_context}" if effectiveness_context else ""
        )
        user_content = date_header + query + memory_section + incident_section + effectiveness_section
        user_content += goal_section

        last_exc: Exception | None = None
        for attempt in range(1, self._get_max_retries() + 1):
            try:
                transport_cfg = get_mcp_transport_config()
                mode = "SSE" if transport_cfg.get("transport") == "sse" else "stdio subprocess"
                log.info("[%s] Attempt %d/%d — connecting to MCP via %s (query_type=%s)...",
                         agent_name, attempt, self._get_max_retries(), mode, query_type)

                client = MultiServerMCPClient({"ecommerce-ops": transport_cfg})
                all_tools = await client.get_tools()
                filtered = [t for t in all_tools if t.name in self._get_tool_names()]
                log.info("[%s] MCP connected — %d tools loaded: %s",
                         agent_name, len(filtered), [t.name for t in filtered])

                write_tool_names = self._get_write_tool_names()

                # Strip write tools from the live tool node so the LLM cannot
                # invoke them directly during analysis. Write tools are communicated
                # to the LLM only via the prompt suffix (proposed_actions schema),
                # never as callable tools in the ReAct loop.
                read_only_filtered = [t for t in filtered if t.name not in set(write_tool_names)]
                if len(read_only_filtered) < len(filtered):
                    stripped = [t.name for t in filtered if t.name in set(write_tool_names)]
                    log.info("[%s] 🔒 Write tools stripped from ReAct tool node (propose-only): %s",
                             agent_name, stripped)

                # For non-ACTION queries, prepend the override BEFORE the agent's
                # own system_prompt so it outranks any hardcoded "PROPOSE action"
                # conditionals in the domain-specific instructions below it.
                if query_type != "ACTION":
                    override = (
                        f"CRITICAL OVERRIDE — {query_type} QUERY: "
                        "You are operating in read-only analysis mode for this run. "
                        "Call all your read tools to gather data as normal. "
                        "Do NOT propose any write actions regardless of what you find. "
                        "The proposed_actions JSON block must always be empty [].\n\n"
                    )
                    full_prompt = override + self._get_system_prompt() + self._build_actions_suffix(write_tool_names, query_type)
                else:
                    full_prompt = self._get_system_prompt() + self._build_actions_suffix(write_tool_names, query_type)
                llm = self._build_llm()
                graph = create_agent(llm, read_only_filtered, system_prompt=full_prompt)

                log.info("[%s] Invoking ReAct loop (timeout=%ds)...", agent_name, self._get_react_timeout())
                agent_input = {"messages": [HumanMessage(content=user_content)]}
                result = await asyncio.wait_for(graph.ainvoke(agent_input), timeout=self._get_react_timeout())

                messages = result.get("messages", [])
                tool_calls_made = sum(1 for m in messages if getattr(m, "tool_calls", None))
                log.info("[%s] ReAct loop complete — %d tool call(s) in %.1fs",
                         agent_name, tool_calls_made, time.perf_counter() - t0)

                # Extract the final AI message
                final_text = ""
                for msg in reversed(messages):
                    if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                        final_text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                        break

                # Parse the structured proposed_actions JSON block from the response
                proposed_actions: list[dict] = []
                match = re.search(r"```json\s*(\{.*?\})\s*```", final_text, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(1))
                        raw_actions = parsed.get("proposed_actions", [])

                        # Strict validation: only keep actions whose name exactly
                        # matches a registered write tool.  This ensures the execute
                        # node never receives hallucinated or namespace-prefixed names
                        # (e.g. "functions.create_priority_dev_ticket").  Mismatches
                        # are surfaced here — close to the LLM output — rather than
                        # silently normalised at execution time.
                        allowed_write_tools: set[str] = set(write_tool_names)
                        for act in raw_actions:
                            name = act.get("action", "")
                            if name in allowed_write_tools:
                                proposed_actions.append(act)
                            else:
                                log.error(
                                    "[%s] Proposed action '%s' is not a registered write tool "
                                    "— dropping. Allowed: %s",
                                    agent_name, name, sorted(allowed_write_tools),
                                )

                        log.info("[%s] %d/%d proposed action(s) passed validation",
                                 agent_name, len(proposed_actions), len(raw_actions))
                    except json.JSONDecodeError as exc:
                        log.warning("[%s] Failed to parse proposed_actions JSON: %s", agent_name, exc)
                else:
                    log.info("[%s] No proposed_actions JSON block found in response", agent_name)

                return {
                    "discoveries": [final_text] if final_text else [],
                    "proposed_actions": proposed_actions,
                }

            except asyncio.TimeoutError as exc:
                last_exc = exc
                remaining = self._get_max_retries() - attempt
                if remaining:
                    log.warning("[%s] Timed out on attempt %d — retrying in 5s (%d left)...",
                                agent_name, attempt, remaining)
                    await asyncio.sleep(5)
                else:
                    log.error("[%s] Timed out on all %d attempts (%.1fs elapsed)",
                              agent_name, self._get_max_retries(), time.perf_counter() - t0)

            except Exception as exc:
                last_exc = exc
                remaining = self._get_max_retries() - attempt
                if remaining:
                    log.warning("[%s] Error on attempt %d (%s) — retrying in 5s (%d left)...",
                                agent_name, attempt, exc, remaining)
                    await asyncio.sleep(5)
                else:
                    log.error("[%s] Failed on all %d attempts: %s", agent_name, self._get_max_retries(), exc)

        raise RuntimeError(
            f"{agent_name} failed after {self._get_max_retries()} attempt(s): {last_exc}"
        )

    async def retrospect(
        self,
        domain: str,
        prior_findings: list[str],
        prior_actions: list[dict],
        peer_whiteboard: dict,
        query: str,
        agent_goal: str = "",
        query_type: str = "ACTION",
    ) -> dict[str, Any]:
        """Collaborative retrospection pass.

        Called after all agents complete Phase 1.  Each agent receives the
        full cross-agent whiteboard (its own findings PLUS all peers) and is
        asked to:

        1. Revise its findings if a peer discovery changes the picture.
        2. Add new findings if a peer's data reveals a blind spot.
        3. Update, add, or drop proposed actions in light of peer context.
        4. Call its read tools again if it needs more data to verify.

        Parameters
        ----------
        domain : str
            This agent's domain key (e.g. "inventory").
        prior_findings : list[str]
            The text findings this agent produced in Phase 1.
        prior_actions : list[dict]
            The proposed_actions this agent drafted in Phase 1.
        peer_whiteboard : dict
            Full whiteboard dict keyed by domain, including all other agents.
        query : str
            Original user query for context.

        Returns
        -------
        dict with keys ``discoveries`` (list[str]) and ``proposed_actions``
        (list[dict]).  Empty lists mean "no revisions needed".
        """
        from langchain_core.messages import HumanMessage
        from langchain_mcp_adapters.client import MultiServerMCPClient

        agent_name = self.__class__.__name__
        t0 = time.perf_counter()

        # Build peer findings text (exclude own domain)
        peer_text_parts = []
        for d, data in peer_whiteboard.items():
            if d == domain or d in ("reflection", "final_report", "execution_result"):
                continue
            findings = data.get("findings", [])
            if findings:
                peer_text_parts.append(
                    f"=== {d.upper()} AGENT FINDINGS ===\n" + "\n".join(
                        str(f) for f in findings
                    )
                )
        peer_text = "\n\n".join(peer_text_parts) or "No peer findings available."

        own_text = "\n".join(str(f) for f in prior_findings) or "No prior findings."
        own_actions_text = json.dumps(prior_actions, indent=2) if prior_actions else "[]"

        write_tool_names: list[str] = getattr(self, "write_tool_names", [])

        # Build query_type-aware action constraint and output block
        if query_type != "ACTION":
            action_constraint = (
                f"This is a {query_type} query — do NOT propose any write actions. "
                "Always output an empty proposed_actions array."
            )
            output_format_block = f"""---
OUTPUT FORMAT (mandatory at the end):
Call read tools if needed to verify cross-domain findings.
This is a {query_type} query — always output this exact block:

```json
{{
  "proposed_actions": []
}}
```"""
        else:
            action_constraint = (
                f"You may still propose actions using these tool names: {write_tool_names}"
                if write_tool_names
                else "You have no write tools — keep proposed_actions as an empty array."
            )
            output_format_block = """---
OUTPUT FORMAT (mandatory at the end):
```json
{
  "proposed_actions": [
    {
      "action": "<exact_tool_name>",
      "reason": "<one sentence, including cross-domain context if relevant>",
      "params": {"<param>": "<value>"}
    }
  ]
}
```"""

        goal_line = f"\nYOUR SPECIFIC GOAL: {agent_goal}" if agent_goal else ""
        retro_prompt = f"""You are the {domain.upper()} domain agent performing a COLLABORATIVE RETROSPECTION.

ORIGINAL QUERY: {query}{goal_line}

YOUR PHASE 1 FINDINGS:
{own_text}

YOUR DRAFT PROPOSED ACTIONS:
{own_actions_text}

YOUR PEERS' FINDINGS (from all other domain agents):
{peer_text}

---
YOUR TASK:
1. Read your peers' findings carefully. Do any of them contradict, confirm, or add context to your own analysis?
2. If you spot a cross-domain issue (e.g., a stockout your peer found that directly affects your domain), revise your findings to mention it explicitly.
3. If a peer's finding makes one of your proposed actions MORE urgent — update it. If it makes an action REDUNDANT — drop it.
4. If you need more data to verify a cross-domain hypothesis, call your available read tools now.
5. If everything looks consistent and correct, restate your prior findings with a note confirming they hold.

{action_constraint}

{output_format_block}"""

        retro_timeout = max(60, self.react_timeout - 30)

        try:
            log.info("[%s][RETROSPECT] Starting retrospection (timeout=%ds)...",
                     agent_name, retro_timeout)

            transport_cfg = get_mcp_transport_config()
            client = MultiServerMCPClient({"ecommerce-ops": transport_cfg})
            all_tools = await client.get_tools()
            # Only read tools during retrospection — never write tools.
            # Use _get_tool_names() (not self.tool_names) so config-based agents
            # get their full allow-list. Include resolve_ so identifier-resolution
            # tools are available for cross-domain verification.
            read_prefixes = ("get_", "check_", "search_", "query_", "resolve_")
            agent_tool_names = set(self._get_tool_names())
            read_tools = [
                t for t in all_tools
                if t.name in agent_tool_names and any(t.name.startswith(p) for p in read_prefixes)
            ]
            log.info("[%s][RETROSPECT] %d read tool(s) available for verification",
                     agent_name, len(read_tools))

            llm = self._build_llm()
            retro_graph = create_agent(llm, read_tools, system_prompt=retro_prompt)

            retro_result = await asyncio.wait_for(
                retro_graph.ainvoke({"messages": [HumanMessage(content="Begin retrospection.")]}),
                timeout=retro_timeout,
            )

            messages = retro_result.get("messages", [])
            final_text = ""
            for msg in reversed(messages):
                if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                    final_text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                    break

            revised_actions: list[dict] = []
            match = re.search(r"```json\s*(\{.*?\})\s*```", final_text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                    revised_actions = parsed.get("proposed_actions", [])
                except json.JSONDecodeError:
                    pass

            tool_calls_made = sum(1 for m in messages if getattr(m, "tool_calls", None))
            log.info("[%s][RETROSPECT] Done — %d tool call(s), %d revised action(s) in %.1fs",
                     agent_name, tool_calls_made, len(revised_actions), time.perf_counter() - t0)

            return {
                "discoveries": [final_text] if final_text else prior_findings,
                "proposed_actions": revised_actions,
            }

        except Exception as exc:
            log.warning("[%s][RETROSPECT] Failed (%s) — keeping Phase 1 results unchanged",
                        agent_name, exc)
            return {
                "discoveries": prior_findings,
                "proposed_actions": prior_actions,
            }

