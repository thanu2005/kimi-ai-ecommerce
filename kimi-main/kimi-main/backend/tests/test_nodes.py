"""Node source-contract tests.

Guards behavioral invariants in each orchestrator node without importing
heavy runtime dependencies. Each test reads the Python source file and
asserts critical structural patterns are present.
"""

from __future__ import annotations

from pathlib import Path

_NODES_DIR = Path(__file__).resolve().parents[1] / "app" / "agents" / "orchestrator" / "nodes"


def _node(name: str) -> str:
    return (_NODES_DIR / name).read_text(encoding="utf-8")


# ===========================================================================
# guard_node
# ===========================================================================

class TestGuardNode:
    def test_guard_returns_off_topic_true_when_irrelevant(self) -> None:
        src = _node("guard.py")
        assert '"off_topic": True' in src

    def test_guard_returns_off_topic_false_when_relevant(self) -> None:
        src = _node("guard.py")
        assert '"off_topic": False' in src

    def test_guard_defaults_to_relevant_on_llm_failure(self) -> None:
        src = _node("guard.py")
        assert "is_relevant = True" in src
        assert "except Exception" in src

    def test_guard_includes_history_snippet_for_followup_classification(self) -> None:
        src = _node("guard.py")
        assert "history_snippet" in src
        assert "Prior conversation" in src

    def test_guard_route_function_maps_off_topic_correctly(self) -> None:
        src = _node("guard.py")
        assert 'def _route_from_guard' in src
        assert 'state.get("off_topic")' in src
        assert '"off_topic"' in src or "'off_topic'" in src
        assert '"supervisor"' in src or "'supervisor'" in src

    def test_guard_writes_rejection_to_whiteboard(self) -> None:
        src = _node("guard.py")
        assert '"formatted_response"' in src
        assert "_REJECTION" in src


# ===========================================================================
# supervisor_node
# ===========================================================================

class TestSupervisorNode:
    def test_supervisor_writes_memory_flags(self) -> None:
        src = _node("supervisor.py")
        assert '"needs_incident_memory": needs_incident_memory' in src
        assert '"needs_action_effectiveness": needs_action_effectiveness' in src

    def test_supervisor_uses_intent_flags_not_hardcoded_cues(self) -> None:
        src = _node("supervisor.py")
        assert "_HISTORY_QUERY_CUES" not in src
        assert "_ACTION_EFFECTIVENESS_QUERY_CUES" not in src

    def test_supervisor_sets_selected_agents(self) -> None:
        src = _node("supervisor.py")
        assert "selected_agents" in src

    def test_supervisor_sets_agent_goals(self) -> None:
        src = _node("supervisor.py")
        assert "agent_goals" in src


# ===========================================================================
# domain_scan_node (parallel_domain_scan_node)
# ===========================================================================

class TestDomainScanNode:
    def test_domain_scan_handles_timeout(self) -> None:
        src = _node("domain_scan.py")
        assert "asyncio.TimeoutError" in src

    def test_domain_scan_handles_generic_exception(self) -> None:
        src = _node("domain_scan.py")
        assert "except Exception" in src

    def test_domain_scan_maps_all_four_agents(self) -> None:
        src = _node("domain_scan.py")
        for domain in ("inventory", "sales", "marketing", "support"):
            assert domain in src

    def test_domain_scan_returns_whiteboard_findings(self) -> None:
        src = _node("domain_scan.py")
        assert '"findings"' in src or "'findings'" in src

    def test_domain_scan_returns_proposed_actions(self) -> None:
        src = _node("domain_scan.py")
        assert '"proposed_actions"' in src or "'proposed_actions'" in src

    def test_domain_scan_is_async(self) -> None:
        src = _node("domain_scan.py")
        assert "async def parallel_domain_scan_node" in src


# ===========================================================================
# retrospection_node (collaborative_retrospection_node)
# ===========================================================================

class TestRetrospectionNode:
    def test_retrospection_uses_asyncio_gather(self) -> None:
        src = _node("retrospection.py")
        assert "asyncio.gather" in src

    def test_retrospection_handles_generic_exception(self) -> None:
        src = _node("retrospection.py")
        assert "except Exception" in src

    def test_retrospection_maps_all_four_agents(self) -> None:
        src = _node("retrospection.py")
        for domain in ("inventory", "sales", "marketing", "support"):
            assert domain in src

    def test_retrospection_reads_prior_findings_from_whiteboard(self) -> None:
        src = _node("retrospection.py")
        assert "whiteboard" in src
        assert "prior_findings" in src or "findings" in src

    def test_retrospection_is_async(self) -> None:
        src = _node("retrospection.py")
        assert "async def collaborative_retrospection_node" in src


# ===========================================================================
# synthesizer_node
# ===========================================================================

class TestSynthesizerNode:
    def test_synthesizer_reads_whiteboard(self) -> None:
        src = _node("synthesizer.py")
        assert 'state.get("whiteboard")' in src

    def test_synthesizer_reads_proposed_actions(self) -> None:
        src = _node("synthesizer.py")
        assert 'state.get("proposed_actions")' in src

    def test_synthesizer_reads_query_type(self) -> None:
        src = _node("synthesizer.py")
        assert "query_type" in src

    def test_synthesizer_includes_memory_context(self) -> None:
        src = _node("synthesizer.py")
        assert "memory_context" in src

    def test_synthesizer_includes_action_effectiveness_context(self) -> None:
        src = _node("synthesizer.py")
        assert "action_effectiveness_context" in src

    def test_synthesizer_route_function_present(self) -> None:
        src = _node("synthesizer.py")
        assert "_route_after_synthesis" in src

    def test_synthesizer_is_async(self) -> None:
        src = _node("synthesizer.py")
        assert "async def synthesizer_node" in src


# ===========================================================================
# hitl_gateway_node
# ===========================================================================

class TestHITLGatewayNode:
    def test_hitl_gateway_returns_empty_dict(self) -> None:
        src = _node("hitl_gateway.py")
        assert "return {}" in src

    def test_hitl_route_blocks_without_human_reviewed_flag(self) -> None:
        src = _node("hitl_gateway.py")
        assert 'state.get("hitl_human_reviewed")' in src

    def test_hitl_route_sends_rejected_actions_to_supervisor(self) -> None:
        src = _node("hitl_gateway.py")
        assert 'state.get("rejected_actions")' in src
        assert '"supervisor"' in src or "'supervisor'" in src

    def test_hitl_route_sends_approved_to_execute(self) -> None:
        src = _node("hitl_gateway.py")
        assert '"execute_approved_actions"' in src or "'execute_approved_actions'" in src

    def test_hitl_safety_log_on_unreviewed_state(self) -> None:
        src = _node("hitl_gateway.py")
        assert "SAFETY BLOCK" in src or "hitl_human_reviewed is False" in src


# ===========================================================================
# execute_approved_actions_node
# ===========================================================================

class TestExecuteNode:
    def test_execute_sanitizes_tool_params(self) -> None:
        src = _node("execute.py")
        assert "_sanitize_tool_params" in src

    def test_execute_drops_unknown_kwargs(self) -> None:
        src = _node("execute.py")
        assert "allowed_fields" in src

    def test_execute_stores_results_in_whiteboard(self) -> None:
        src = _node("execute.py")
        assert "execution_result" in src

    def test_execute_is_async(self) -> None:
        src = _node("execute.py")
        assert "async def execute_approved_actions_node" in src


# ===========================================================================
# response_formatter_node
# ===========================================================================

class TestResponseFormatterNode:
    def test_response_formatter_reads_query(self) -> None:
        src = _node("response_formatter.py")
        assert 'state.get("query"' in src

    def test_response_formatter_has_section_rules(self) -> None:
        src = _node("response_formatter.py")
        # The system prompt defines formatting rules
        assert "Key Findings" in src

    def test_response_formatter_conditionally_adds_actions_taken(self) -> None:
        src = _node("response_formatter.py")
        assert "Actions Taken" in src
        # Must NOT blindly include it — relies on EXECUTION RESULTS presence
        assert "EXECUTION RESULTS" in src

    def test_response_formatter_is_async(self) -> None:
        src = _node("response_formatter.py")
        assert "async def response_formatter_node" in src
