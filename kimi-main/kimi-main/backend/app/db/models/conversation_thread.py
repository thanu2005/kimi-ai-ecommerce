"""conversation_threads — top-level conversation containers for chat sidebar."""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ConversationThread(SQLModel, table=True):
    """Stores one row per conversation thread."""

    __tablename__ = "conversation_threads"

    thread_id: str = Field(primary_key=True, max_length=128)
    title: str = Field(max_length=255, default="New conversation")
    last_run_id: Optional[str] = Field(default=None, max_length=64, index=True)
    last_status: Optional[str] = Field(default=None, max_length=32, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
