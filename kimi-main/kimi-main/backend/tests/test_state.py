"""State schema source-contract tests.

Ensures ``OrchestratorState`` and ``SubAgentState`` declare all required fields
and that the state module satisfies the whiteboard contract documented in its
docstring. No heavy imports — reads the Python source directly.
"""

from __future__ import annotations

from pathlib import Path


def _src() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "app" / "agents" / "state.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# OrchestratorState required fields
# ---------------------------------------------------------------------------

ORCHESTRATOR_REQUIRED_FIELDS = [
    "query",
    "session_id",
    "intent",
    "selected_agents",
    "whiteboard",
    "orchestrator_goals",
    "agent_goals",
    "memory_context",
    "incident_memory_context",
    "action_effectiveness_context",
    "messages",
    "proposed_actions",
    "pending_execution",
    "rejected_actions",
    "human_note",
    "iteration",
    "retry_domains",
    "formatted_response",
    "off_topic",
    "query_type",
    "requires_remediation",
    "needs_incident_memory",
    "needs_action_effectiveness",
    "hitl_human_reviewed",
]


def test_orchestrator_state_declares_all_required_fields() -> None:
    src = _src()
    for field in ORCHESTRATOR_REQUIRED_FIELDS:
        assert field in src, f"OrchestratorState missing field: {field}"


def test_orchestrator_state_uses_typed_dict() -> None:
    src = _src()
    assert "class OrchestratorState(TypedDict)" in src


def test_orchestrator_state_messages_uses_operator_add_reducer() -> None:
    """Messages must accumulate across node transitions, not be overwritten."""
    src = _src()
    assert "operator.add" in src
    assert "Annotated[list, operator.add]" in src


# ---------------------------------------------------------------------------
# SubAgentState required fields
# ---------------------------------------------------------------------------

SUB_AGENT_REQUIRED_FIELDS = [
    "messages",
    "query",
    "memory_context",
    "incident_memory_context",
    "action_effectiveness_context",
    "discoveries",
    "agent_goal",
]


def test_sub_agent_state_declares_required_fields() -> None:
    src = _src()
    for field in SUB_AGENT_REQUIRED_FIELDS:
        assert field in src, f"SubAgentState missing field: {field}"


def test_sub_agent_state_uses_typed_dict() -> None:
    src = _src()
    assert "class SubAgentState(TypedDict)" in src


# ---------------------------------------------------------------------------
# HITL / safety fields
# ---------------------------------------------------------------------------

def test_hitl_human_reviewed_is_bool_typed() -> None:
    src = _src()
    assert "hitl_human_reviewed: bool" in src


def test_off_topic_is_bool_typed() -> None:
    src = _src()
    assert "off_topic: bool" in src


def test_needs_incident_memory_is_bool_typed() -> None:
    src = _src()
    assert "needs_incident_memory: bool" in src


def test_needs_action_effectiveness_is_bool_typed() -> None:
    src = _src()
    assert "needs_action_effectiveness: bool" in src


def test_iteration_counter_is_int_typed() -> None:
    src = _src()
    assert "iteration: int" in src


# ---------------------------------------------------------------------------
# Whiteboard contract documentation
# ---------------------------------------------------------------------------

def test_state_module_documents_whiteboard_contract() -> None:
    src = _src()
    assert "whiteboard" in src
    # The module docstring should mention both inventory and sales namespaces
    assert "inventory" in src
    assert "sales" in src
