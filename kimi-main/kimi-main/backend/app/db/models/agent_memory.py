"""Long-term memory tables for orchestrator runs and incident intelligence."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


class AgentRunMemory(SQLModel, table=True):
    """Stores run-level memory for each thread.

    Each row captures both a compact summary and a full detailed snapshot,
    then links to vectorized artifacts in Qdrant for semantic retrieval.
    """

    __tablename__ = "agent_run_memories"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, unique=True, max_length=64)
    thread_id: str = Field(index=True, max_length=128)
    query_text: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(index=True, max_length=32)

    summary_text: str = Field(sa_column=Column(Text, nullable=False))
    detailed_text: str = Field(sa_column=Column(Text, nullable=False))

    whiteboard_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    proposed_actions_json: list[dict[str, Any]] = Field(
        sa_column=Column(JSON, nullable=False),
        default_factory=list,
    )
    execution_result_json: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    vectorized_at: Optional[datetime] = Field(default=None, index=True)


class IncidentMemory(SQLModel, table=True):
    """Stores normalized incident snapshots for cross-thread precedent lookup.

    This schema powers questions such as:
    - Has this happened before?
    - What actions worked best previously?
    """

    __tablename__ = "incident_memories"

    id: Optional[int] = Field(default=None, primary_key=True)
    incident_id: str = Field(index=True, unique=True, max_length=80)
    run_id: str = Field(index=True, max_length=64)
    thread_id: str = Field(index=True, max_length=128)
    query_text: str = Field(sa_column=Column(Text, nullable=False))

    incident_type: str = Field(index=True, max_length=64)
    severity: str = Field(index=True, max_length=32, default="MEDIUM")
    time_window: Optional[str] = Field(default=None, max_length=64)

    domains_json: list[str] = Field(sa_column=Column(JSON, nullable=False), default_factory=list)
    symptoms_text: str = Field(sa_column=Column(Text, nullable=False))
    root_cause_text: str = Field(sa_column=Column(Text, nullable=False), default="")

    actions_executed_json: list[dict[str, Any]] = Field(
        sa_column=Column(JSON, nullable=False),
        default_factory=list,
    )
    outcome_metrics_json: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False),
        default_factory=dict,
    )
    outcome_label: str = Field(index=True, max_length=24, default="UNKNOWN")

    evidence_refs_json: list[dict[str, Any]] = Field(
        sa_column=Column(JSON, nullable=False),
        default_factory=list,
    )

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    vectorized_at: Optional[datetime] = Field(default=None, index=True)
