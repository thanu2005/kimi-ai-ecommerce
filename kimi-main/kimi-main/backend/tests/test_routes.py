"""Analysis route source-contract tests."""

from __future__ import annotations

from pathlib import Path


def _read_analysis_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "app" / "routes" / "v1" / "analysis.py").read_text(encoding="utf-8")


def test_analysis_uses_intent_flag_for_leaderboard() -> None:
    src = _read_analysis_source()
    assert '_should_include_action_effectiveness' in src
    assert 'state.get("needs_action_effectiveness", False)' in src


def test_analysis_no_hardcoded_action_effectiveness_cues() -> None:
    src = _read_analysis_source()
    assert '_ACTION_EFFECTIVENESS_QUERY_CUES' not in src
    assert '_asks_action_effectiveness' not in src
