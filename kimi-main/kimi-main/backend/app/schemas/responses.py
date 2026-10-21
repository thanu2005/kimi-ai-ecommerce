"""Response schemas for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ConversationListResponse(BaseModel):
    """List of conversation threads."""
    conversations: list[dict[str, Any]]


class ConversationMessagesResponse(BaseModel):
    """Messages for a single conversation thread."""
    thread_id: str
    messages: list[dict[str, Any]]
