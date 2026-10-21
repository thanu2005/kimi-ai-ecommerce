"""Conversation history endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import ConversationListResponse, ConversationMessagesResponse
from app.services.conversation_history import (
    get_conversation_messages,
    list_conversations,
)

router = APIRouter(prefix="/api", tags=["conversations"])


@router.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(limit: int = 50) -> ConversationListResponse:
    """Return sidebar-ready conversation thread list ordered by recency."""
    rows = await list_conversations(limit=limit)
    return ConversationListResponse(conversations=rows)


@router.get("/conversations/{thread_id}/messages", response_model=ConversationMessagesResponse)
async def get_conversation_history(thread_id: str, limit: int = 200) -> ConversationMessagesResponse:
    """Return chat messages for one thread in chronological order."""
    rows = await get_conversation_messages(thread_id=thread_id, limit=limit)
    return ConversationMessagesResponse(thread_id=thread_id, messages=rows)
