"""Request schemas for the API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class RunRequest(BaseModel):
    """Trigger a full multi-agent analysis run."""
    query: str = "Perform a full operational health check for today."
    thread_id: Optional[str] = None


class ResumeRequest(BaseModel):
    """Resume a paused graph after operator approval."""
    thread_id: str
    approved_actions: list[dict]
    rejected_actions: list[dict] = []
    human_note: str = ""
    run_id: Optional[str] = None
