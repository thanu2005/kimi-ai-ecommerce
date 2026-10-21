"""Graph assembly source-contract tests.

Validates the wiring of nodes, edges, and routing functions inside
``app/agents/orchestrator/graph.py`` without importing any heavy
runtime dependencies (LangGraph, LLMs, DB).
"""

from __future__ import annotations

from pathlib import Path


def _src() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "app" / "agents" / "orchestrator" / "graph.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Node registration
# ---------------------------------------------------------------------------

def test_all_required_nodes_are_registered() -> None:
    src = _src()
    for node in (
        '"guard"',
        '"supervisor"',
        '"parallel_domain_scan"',
        '"collaborative_retrospection"',
        '"synthesizer"',
        '"hitl_gateway"',
        '"execute_approved_actions"',
        '"response_formatter"',
    ):
        assert node in src, f"Node {node} not registered in graph"


# ---------------------------------------------------------------------------
# Edge wiring
# ---------------------------------------------------------------------------

def test_graph_starts_at_guard() -> None:
    src = _src()
    assert 'add_edge(START, "guard")' in src


def test_supervisor_leads_to_domain_scan() -> None:
    src = _src()
    assert 'add_edge("supervisor", "parallel_domain_scan")' in src


def test_domain_scan_leads_to_retrospection() -> None:
    src = _src()
    assert 'add_edge("parallel_domain_scan", "collaborative_retrospection")' in src


def test_retrospection_leads_to_synthesizer() -> None:
    src = _src()
    assert 'add_edge("collaborative_retrospection", "synthesizer")' in src


def test_execute_leads_to_response_formatter() -> None:
    src = _src()
    assert 'add_edge("execute_approved_actions", "response_formatter")' in src


def test_response_formatter_leads_to_end() -> None:
    src = _src()
    assert 'add_edge("response_formatter", END)' in src


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------

def test_guard_has_conditional_edge_to_supervisor_and_off_topic() -> None:
    src = _src()
    assert '"supervisor": "supervisor"' in src
    assert '"off_topic": END' in src


def test_synthesizer_has_conditional_edge_to_hitl_and_end() -> None:
    src = _src()
    assert '"hitl_gateway": "hitl_gateway"' in src
    assert 'END: "response_formatter"' in src


def test_hitl_has_conditional_edge_to_supervisor_and_execute() -> None:
    src = _src()
    assert '"supervisor": "supervisor"' in src
    assert '"execute_approved_actions": "execute_approved_actions"' in src


# ---------------------------------------------------------------------------
# HITL interrupt configuration
# ---------------------------------------------------------------------------

def test_graph_compiled_with_interrupt_before_hitl_gateway() -> None:
    src = _src()
    assert 'interrupt_before=["hitl_gateway"]' in src


def test_build_supervisor_graph_accepts_checkpointer_param() -> None:
    src = _src()
    assert "def build_supervisor_graph(checkpointer=None)" in src
    assert "checkpointer=checkpointer" in src


# ---------------------------------------------------------------------------
# Routing function presence
# ---------------------------------------------------------------------------

def test_routing_functions_are_imported() -> None:
    src = _src()
    assert "_route_after_synthesis" in src
    assert "_route_from_guard" in src
    assert "_route_from_hitl_gateway" in src
