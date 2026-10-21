"""Graph assembly — wires all orchestrator nodes into the LangGraph StateGraph."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.orchestrator.nodes import (
    _route_after_synthesis,
    _route_from_guard,
    _route_from_hitl_gateway,
    collaborative_retrospection_node,
    execute_approved_actions_node,
    guard_node,
    hitl_gateway_node,
    parallel_domain_scan_node,
    response_formatter_node,
    supervisor_node,
    synthesizer_node,
)
from app.agents.state import OrchestratorState


def build_supervisor_graph(checkpointer=None):
    """Assemble and compile the full supervisor orchestration graph.

    Parameters
    ----------
    checkpointer : AsyncPostgresSaver | None
        LangGraph checkpoint backend.  Pass ``AsyncPostgresSaver`` for
        persistent HITL support.  Pass ``None`` for stateless testing.

    Returns
    -------
    CompiledGraph
        The compiled supervisor graph ready for ``ainvoke`` / ``astream``.
    """
    graph = StateGraph(OrchestratorState)

    graph.add_node("guard", guard_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("parallel_domain_scan", parallel_domain_scan_node)
    graph.add_node("collaborative_retrospection", collaborative_retrospection_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("hitl_gateway", hitl_gateway_node)
    graph.add_node("execute_approved_actions", execute_approved_actions_node)
    graph.add_node("response_formatter", response_formatter_node)

    graph.add_edge(START, "guard")
    graph.add_conditional_edges(
        "guard",
        _route_from_guard,
        {"supervisor": "supervisor", "off_topic": END},
    )
    graph.add_edge("supervisor", "parallel_domain_scan")
    graph.add_edge("parallel_domain_scan", "collaborative_retrospection")
    graph.add_edge("collaborative_retrospection", "synthesizer")
    graph.add_conditional_edges(
        "synthesizer",
        _route_after_synthesis,
        {"hitl_gateway": "hitl_gateway", END: "response_formatter"},
    )
    graph.add_conditional_edges(
        "hitl_gateway",
        _route_from_hitl_gateway,
        {
            "supervisor": "supervisor",
            "execute_approved_actions": "execute_approved_actions",
        },
    )
    graph.add_edge("execute_approved_actions", "response_formatter")
    graph.add_edge("response_formatter", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["hitl_gateway"],
    )
