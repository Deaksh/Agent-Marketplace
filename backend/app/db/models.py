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


class Org(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=_now_utc)


class AgentPackage(SQLModel, table=True):
    """
    Stable identity for an agent across versions (marketplace-facing).
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    publisher: str = Field(index=True)  # e.g. org/user handle
    slug: str = Field(index=True, unique=True)  # stable URL-friendly id
    name: str
    description: str = ""
    categories: list[str] = Field(default_factory=list, sa_column=Column(SQLITE_JSON))
    tags: list[str] = Field(default_factory=list, sa_column=Column(SQLITE_JSON))
    created_at: datetime = Field(default_factory=_now_utc, index=True)


class AgentVersion(SQLModel, table=True):
    """
    Immutable (in spirit) version record for a package.

    v1 supports three runtimes:
    - builtin: maps to a built-in agent name
    - remote_http: POST JSON to an HTTPS endpoint
    - llm_prompt: run Groq/OpenAI-compatible prompt returning JSON
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    package_id: UUID = Field(index=True)

    version: str = Field(index=True)  # semver-like string
    release_notes: str = ""

    runtime: str = Field(index=True)  # builtin|remote_http|llm_prompt
    builtin_agent_name: str | None = Field(default=None, index=True)
    endpoint_url: str | None = None
    prompt_template: str | None = None

    input_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    output_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    cost_estimate_usd: float = 0.0
    reliability_score: float = 0.8  # 0..1

    status: str = Field(default="active", index=True)  # active|disabled|deprecated
    created_at: datetime = Field(default_factory=_now_utc, index=True)

    # Minimal marketplace signals (v1)
    run_count: int = 0
    success_count: int = 0
    avg_latency_ms: float = 0.0


class OrgAgentEnablement(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(index=True)
    package_id: UUID = Field(index=True)
    enabled: bool = True
    pinned_version_id: UUID | None = Field(default=None, index=True)
    policy: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    created_at: datetime = Field(default_factory=_now_utc, index=True)


class Execution(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID | None = Field(default=None, index=True)
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
    agent_package_id: UUID | None = Field(default=None, index=True)
    agent_version_id: UUID | None = Field(default=None, index=True)
    cost_usd_estimated: float | None = None
    cost_usd_actual: float | None = None
    status: str = "queued"  # queued|running|succeeded|failed|skipped
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempts: int = 0

    input: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    output: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))
    error: Optional[str] = None


class AuditLog(SQLModel, table=True):
    """
    Append-only audit event stream.

    This is intentionally denormalized JSON so we can:
    - record execution + step lifecycle events
    - keep a durable explainability trail even if agent outputs evolve
    - support future marketplace provenance (signatures, package hashes, etc.)
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    execution_id: UUID = Field(index=True)
    step_id: Optional[UUID] = Field(default=None, index=True)

    event_type: str = Field(index=True)  # execution.* | step.* | system.*
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SQLITE_JSON))

    created_at: datetime = Field(default_factory=_now_utc, index=True)


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

