"""Conversation history service for sidebar and chat transcript rendering."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select

from app.db.models.conversation_message import ConversationMessage
from app.db.models.conversation_thread import ConversationThread
from app.db.session import get_session


def _make_title_from_query(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return "New conversation"
    return text[:80] + ("..." if len(text) > 80 else "")


async def ensure_thread(thread_id: str, initial_query: str, run_id: str | None = None) -> None:
    """Create thread row if missing and refresh updated timestamp."""
    now = datetime.utcnow()
    async with get_session() as session:
        result = await session.execute(
            select(ConversationThread).where(ConversationThread.thread_id == thread_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = ConversationThread(
                thread_id=thread_id,
                title=_make_title_from_query(initial_query),
                last_run_id=run_id,
                last_status="awaiting_approval",
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.updated_at = now
            if run_id:
                row.last_run_id = run_id


async def append_message(
    *,
    thread_id: str,
    run_id: str | None,
    role: str,
    message_type: str,
    content: str,
) -> None:
    """Append one message into a conversation thread."""
    now = datetime.utcnow()
    async with get_session() as session:
        msg = ConversationMessage(
            thread_id=thread_id,
            run_id=run_id,
            role=role,
            message_type=message_type,
            content=content,
            created_at=now,
        )
        session.add(msg)

        thread_result = await session.execute(
            select(ConversationThread).where(ConversationThread.thread_id == thread_id)
        )
        thread = thread_result.scalar_one_or_none()
        if thread is not None:
            thread.updated_at = now
            if run_id:
                thread.last_run_id = run_id


async def mark_thread_status(thread_id: str, status: str, run_id: str | None = None) -> None:
    """Update high-level thread status after run/resume transitions."""
    async with get_session() as session:
        result = await session.execute(
            select(ConversationThread).where(ConversationThread.thread_id == thread_id)
        )
        thread = result.scalar_one_or_none()
        if thread is None:
            return
        thread.last_status = status
        thread.updated_at = datetime.utcnow()
        if run_id:
            thread.last_run_id = run_id


async def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    """Return sidebar-ready conversation list ordered by recency."""
    capped = max(1, min(limit, 200))
    async with get_session() as session:
        result = await session.execute(
            select(ConversationThread)
            .order_by(desc(ConversationThread.updated_at))
            .limit(capped)
        )
        threads = result.scalars().all()

        items: list[dict[str, Any]] = []
        for t in threads:
            msg_result = await session.execute(
                select(ConversationMessage)
                .where(ConversationMessage.thread_id == t.thread_id)
                .order_by(desc(ConversationMessage.created_at))
                .limit(1)
            )
            last_msg = msg_result.scalar_one_or_none()
            preview = (last_msg.content[:140] + "...") if last_msg and len(last_msg.content) > 140 else (last_msg.content if last_msg else "")
            items.append(
                {
                    "thread_id": t.thread_id,
                    "title": t.title,
                    "last_status": t.last_status,
                    "last_run_id": t.last_run_id,
                    "last_message_preview": preview,
                    "created_at": t.created_at.isoformat(),
                    "updated_at": t.updated_at.isoformat(),
                }
            )

    return items


async def get_conversation_messages(thread_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """Return chronological messages for a thread for chat rendering."""
    capped = max(1, min(limit, 1000))
    async with get_session() as session:
        result = await session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.thread_id == thread_id)
            .order_by(ConversationMessage.created_at.asc())
            .limit(capped)
        )
        rows = result.scalars().all()

    messages = []
    for r in rows:
        msg_dict = {
            "id": r.id,
            "thread_id": r.thread_id,
            "run_id": r.run_id,
            "role": r.role,
            "message_type": r.message_type,
            "content": r.content,
            "created_at": r.created_at.isoformat(),
        }
        
        # Try to parse JSON payload and extract fields
        if r.role == "assistant":
            try:
                payload = json.loads(r.content)
                if isinstance(payload, dict):
                    # Extract formatted_response if present
                    if "formatted_response" in payload:
                        msg_dict["formatted_response"] = payload.get("formatted_response")
                    # Extract content (use final_report or summary)
                    if "final_report" in payload:
                        msg_dict["content"] = payload.get("final_report", r.content)
                    elif "summary" in payload:
                        msg_dict["content"] = payload.get("summary", r.content)
                    # Extract proposed_actions if present
                    if "proposed_actions" in payload:
                        msg_dict["proposed_actions"] = payload.get("proposed_actions")
                    # Extract executed_actions if present
                    if "executed_actions" in payload:
                        msg_dict["executed_actions"] = payload.get("executed_actions")
                    # Extract action_effectiveness if present
                    if "action_effectiveness" in payload:
                        msg_dict["action_effectiveness"] = payload.get("action_effectiveness")
            except (json.JSONDecodeError, ValueError):
                pass  # Not JSON, use content as-is
        
        messages.append(msg_dict)
    
    return messages


def build_analysis_message(whiteboard: dict[str, Any], proposed_actions: list[dict[str, Any]]) -> str:
    """Create an assistant message body for awaiting-approval phase.
    
    Note: In awaiting_approval state, response_formatter hasn't run yet, so formatted_response
    is empty. We only save metadata here; the frontend will render action cards instead.
    """
    payload = {
        "formatted_response": "",  # Empty during approval phase
        "final_report": "",  # Don't expose raw report with JSON to frontend
        "proposed_actions": proposed_actions,  # Include the full list for action cards
        "proposed_actions_count": len(proposed_actions),
        "message_phase": "awaiting_approval",
    }
    return json.dumps(payload, default=str)


def build_completion_message(
    whiteboard: dict[str, Any],
    executed_actions: list[dict[str, Any]],
    action_effectiveness: dict[str, Any] | None = None,
) -> str:
    """Create an assistant message body for completed phase.
    
    At this point, response_formatter has run and created a clean formatted_response
    without tool names, params, or enriched JSON blocks.
    """
    formatted_response = str(whiteboard.get("formatted_response") or "").strip()
    
    # Fallback if formatter didn't run for some reason
    if not formatted_response:
        formatted_response = "Run completed. Please review the execution results."
    
    payload: dict[str, Any] = {
        "formatted_response": formatted_response,  # Clean response from formatter
        "final_report": "",  # Don't expose raw report
        "executed_actions": executed_actions,  # Include the full list
        "executed_actions_count": len(executed_actions),
        "message_phase": "completed",
    }
    if action_effectiveness:
        payload["action_effectiveness"] = action_effectiveness
    return json.dumps(payload, default=str)
