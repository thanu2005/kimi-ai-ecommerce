"""Intent extraction source-contract tests."""

from __future__ import annotations

from pathlib import Path


def _read_intent_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "app" / "agents" / "orchestrator" / "nodes" / "intent_extraction.py").read_text(encoding="utf-8")


def test_intent_extractor_requests_memory_flags_from_llm_schema() -> None:
    src = _read_intent_source()
    assert '"needs_incident_memory": false' in src
    assert '"needs_action_effectiveness": false' in src
    assert 'needs_incident_memory = true' in src
    assert 'needs_action_effectiveness = true' in src


def test_intent_extractor_parses_and_returns_memory_flags() -> None:
    src = _read_intent_source()
    assert 'parsed.get("needs_incident_memory", False)' in src
    assert 'parsed.get("needs_action_effectiveness", False)' in src
    assert 'return list(_ALL_AGENTS.values()), {}, "REPORT", False, False, False' in src
