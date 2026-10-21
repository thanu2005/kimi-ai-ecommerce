"""conversation_messages — message-by-message history for each thread."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class ConversationMessage(SQLModel, table=True):
    """Stores individual chat messages for a conversation thread."""

    __tablename__ = "conversation_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    thread_id: str = Field(foreign_key="conversation_threads.thread_id", index=True, max_length=128)
    run_id: Optional[str] = Field(default=None, index=True, max_length=64)
    role: str = Field(max_length=32)  # user | assistant | system
    message_type: str = Field(max_length=64)  # query | approval | analysis | completion
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
