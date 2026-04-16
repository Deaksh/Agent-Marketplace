from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.builtin.intent_parser import IntentParserAgent
from app.agents.builtin.obligation_mapper import ObligationMapperAgent
from app.agents.builtin.regulation_retriever import RegulationRetrieverAgent
from app.agents.builtin.report_generator import ReportGeneratorAgent
from app.agents.builtin.risk_scorer import RiskScorerAgent
from app.agents.registry import AgentRegistry, spec_to_dict
from app.core.config import settings
from app.db.models import Agent as AgentRow
from app.db.models import AuditLog, Execution, ExecutionStep, Outcome
from app.db.session import get_session, init_db
from app.orchestrator.orchestrator import Orchestrator
from app.retrieval.regulations import RegulationRetriever
from app.validator.validator import OutcomeValidator


class ExecuteRequest(BaseModel):
    intent: str = Field(..., min_length=3)
    context: dict[str, Any] = Field(default_factory=dict)
    workflow: str | None = None


class ExecuteResponse(BaseModel):
    execution_id: UUID
    status: str
    result: str | None = None
    confidence: float | None = None
    risks: list[dict[str, Any]] | None = None
    recommendations: list[dict[str, Any]] | None = None
    audit_trail: list[dict[str, Any]] | None = None
    explainability: dict[str, Any] | None = None


class RegisterAgentRequest(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    cost_estimate_usd: float = 0.0
    reliability_score: float = 0.8
    enabled: bool = True


async def _ensure_builtin_agents_in_db(*, session: AsyncSession, registry: AgentRegistry) -> None:
    existing = set((await session.execute(select(AgentRow.name))).scalars().all())
    for spec in registry.list_specs():
        if spec.name in existing:
            continue
        session.add(
            AgentRow(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                cost_estimate_usd=spec.cost_estimate_usd,
                reliability_score=spec.reliability_score,
                enabled=True,
            )
        )
    await session.commit()


def _build_registry(*, session: AsyncSession) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(IntentParserAgent())
    registry.register(ObligationMapperAgent())
    registry.register(RiskScorerAgent())
    registry.register(ReportGeneratorAgent())
    registry.register(RegulationRetrieverAgent(RegulationRetriever(session)))
    return registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Seed built-in agents into DB.
    async for session in get_session():
        registry = _build_registry(session=session)
        await _ensure_builtin_agents_in_db(session=session, registry=registry)
        break
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/agents")
async def list_agents(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(AgentRow).order_by(AgentRow.name))).scalars().all()
    return {
        "agents": [
            {
                "name": r.name,
                "description": r.description,
                "input_schema": r.input_schema,
                "output_schema": r.output_schema,
                "cost_estimate_usd": r.cost_estimate_usd,
                "reliability_score": r.reliability_score,
                "enabled": r.enabled,
            }
            for r in rows
        ]
    }


@app.post("/agents/register")
async def register_agent(req: RegisterAgentRequest, session: AsyncSession = Depends(get_session)):
    # Marketplace hook MVP: register metadata only.
    # Actual executable integration comes later via signed agent packages / sandbox.
    existing = (await session.execute(select(AgentRow).where(AgentRow.name == req.name))).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="Agent already exists")
    row = AgentRow(
        name=req.name,
        description=req.description,
        input_schema=req.input_schema,
        output_schema=req.output_schema,
        cost_estimate_usd=req.cost_estimate_usd,
        reliability_score=req.reliability_score,
        enabled=req.enabled,
    )
    session.add(row)
    await session.commit()
    return {"ok": True, "agent": {"name": row.name}}


async def _run_execution(*, execution_id: UUID) -> None:
    async for session in get_session():
        execution = (await session.execute(select(Execution).where(Execution.id == execution_id))).scalars().first()
        if not execution:
            return

        registry = _build_registry(session=session)
        validator = OutcomeValidator()

        def validate(state: dict[str, Any]) -> tuple[float, dict[str, Any]]:
            v = validator.validate(state=state)
            return v.confidence, {"checks": v.checks, "notes": v.notes}

        orch = Orchestrator(registry=registry, session=session, validator=validate)
        await orch.execute(execution=execution)
        return


@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest, background: BackgroundTasks, session: AsyncSession = Depends(get_session)):
    workflow = (req.workflow or req.context.get("workflow") or "auto").strip() if isinstance(req.context, dict) else (req.workflow or "auto")
    execution = Execution(intent=req.intent, context=req.context, workflow=workflow or "auto", status="queued")
    session.add(execution)
    await session.commit()
    await session.refresh(execution)

    # Async-ready execution: run in background task for MVP.
    background.add_task(_run_execution, execution_id=execution.id)

    return ExecuteResponse(execution_id=execution.id, status="queued")


@app.get("/executions/{execution_id}", response_model=ExecuteResponse)
async def get_execution(execution_id: UUID, session: AsyncSession = Depends(get_session)):
    execution = (await session.execute(select(Execution).where(Execution.id == execution_id))).scalars().first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    outcome = (await session.execute(select(Outcome).where(Outcome.execution_id == execution_id))).scalars().first()
    if not outcome:
        return ExecuteResponse(execution_id=execution.id, status=execution.status)

    payload = outcome.result or {}
    return ExecuteResponse(
        execution_id=execution.id,
        status=execution.status,
        result=payload.get("result"),
        confidence=payload.get("confidence"),
        risks=payload.get("risks"),
        recommendations=payload.get("recommendations"),
        audit_trail=payload.get("audit_trail"),
        explainability=payload.get("explainability"),
    )


@app.get("/executions/{execution_id}/steps")
async def list_execution_steps(execution_id: UUID, session: AsyncSession = Depends(get_session)):
    rows = (
        (await session.execute(select(ExecutionStep).where(ExecutionStep.execution_id == execution_id).order_by(ExecutionStep.step_index)))
        .scalars()
        .all()
    )
    return {
        "execution_id": str(execution_id),
        "steps": [
            {
                "id": str(r.id),
                "step_index": r.step_index,
                "agent_name": r.agent_name,
                "status": r.status,
                "attempts": r.attempts,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "error": r.error,
            }
            for r in rows
        ],
    }


@app.get("/executions/{execution_id}/audit")
async def list_execution_audit(execution_id: UUID, session: AsyncSession = Depends(get_session)):
    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.execution_id == execution_id).order_by(AuditLog.created_at)))
        .scalars()
        .all()
    )
    return {
        "execution_id": str(execution_id),
        "events": [
            {
                "id": str(r.id),
                "step_id": str(r.step_id) if r.step_id else None,
                "event_type": r.event_type,
                "message": r.message,
                "payload": r.payload,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }

