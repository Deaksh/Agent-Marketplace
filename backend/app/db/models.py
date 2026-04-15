from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlmodel import Field, SQLModel


def _now_utc() -> datetime:
    return datetime.utcnow()


class Agent(SQLModel, table=True):
    """
    Dynamic agent registry backing store (marketplace hook).

    Built-in agents are registered at startup too, but stored here so that:
    - /agents can return a single unified view
    - future marketplace agents can be injected without redeploying
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    output_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    cost_estimate_usd: float = 0.0
    reliability_score: float = 0.8  # 0..1
    enabled: bool = True
    created_at: datetime = Field(default_factory=_now_utc)


class Execution(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    intent: str
    context: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    workflow: str = "auto"
    status: str = "queued"  # queued|running|succeeded|failed
    created_at: datetime = Field(default_factory=_now_utc)
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class ExecutionStep(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    execution_id: UUID = Field(index=True)
    step_index: int
    agent_name: str
    status: str = "queued"  # queued|running|succeeded|failed|skipped
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempts: int = 0

    input: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    output: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    error: Optional[str] = None


class Outcome(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    execution_id: UUID = Field(index=True)

    result: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    confidence: float = 0.0  # 0..1
    explainability_trace: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    created_at: datetime = Field(default_factory=_now_utc)


# --- Existing system integration (minimal scalable MVP) ---
# These tables are declared so we can reuse ingestion outputs immediately if present.
# For MVP, we keep fields minimal and only rely on "text" for retrieval context.


class RegulationUnit(SQLModel, table=True):
    __tablename__ = "regulation_units"

    id: int | None = Field(default=None, primary_key=True)
    regulation_code: str = Field(index=True)  # e.g. "GDPR"
    unit_id: str = Field(index=True)  # e.g. "Art. 5"
    title: str = ""
    text: str
    version: str = "unknown"
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column("meta", SQLITE_JSON))

