"""Supervisor source-contract tests.

These tests intentionally avoid importing runtime-heavy orchestrator modules,
so they can run in lightweight CI environments while still guarding behavior.
"""

from __future__ import annotations

from pathlib import Path


def _read_supervisor_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "app" / "agents" / "orchestrator" / "nodes" / "supervisor.py").read_text(encoding="utf-8")


def test_supervisor_uses_intent_flags_not_hardcoded_cues() -> None:
    src = _read_supervisor_source()
    assert "_HISTORY_QUERY_CUES" not in src
    assert "_ACTION_EFFECTIVENESS_QUERY_CUES" not in src
    assert "if needs_incident_memory:" in src
    assert "if needs_action_effectiveness:" in src


def test_supervisor_writes_memory_flags_to_state() -> None:
    src = _read_supervisor_source()
    assert '"needs_incident_memory": needs_incident_memory' in src
    assert '"needs_action_effectiveness": needs_action_effectiveness' in src
