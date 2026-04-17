from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.builtin.intent_parser import IntentParserAgent
from app.agents.builtin.obligation_mapper import ObligationMapperAgent
from app.agents.builtin.regulation_retriever import RegulationRetrieverAgent
from app.agents.builtin.report_generator import ReportGeneratorAgent
from app.agents.builtin.risk_scorer import RiskScorerAgent
from app.agents.registry import AgentRegistry, spec_to_dict
from app.core.config import settings
from app.db.models import Agent as AgentRow
from app.db.models import (
    AgentPackage,
    AgentVersion,
    AuditLog,
    Execution,
    ExecutionStep,
    Org,
    OrgAgentEnablement,
    Outcome,
    RegulationUnit,
)
from app.db.session import get_session, init_db
from app.orchestrator.orchestrator import Orchestrator
from app.retrieval.regulations import RegulationRetriever
from app.validator.validator import OutcomeValidator
from app.ingestion.seed_regulations import seed_regulation_units
from app.personas import personas_to_dict


class ExecuteRequest(BaseModel):
    intent: str = Field(..., min_length=3)
    context: dict[str, Any] = Field(default_factory=dict)
    workflow: str | None = None
    org_id: UUID | None = None


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


class PublishAgentVersionRequest(BaseModel):
    publisher: str = Field(..., min_length=2)
    slug: str = Field(..., min_length=2)
    name: str = Field(..., min_length=2)
    description: str = ""
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    version: str = Field(..., min_length=1)
    release_notes: str = ""
    runtime: str = Field(..., min_length=1)  # builtin|remote_http|llm_prompt
    builtin_agent_name: str | None = None
    endpoint_url: str | None = None
    prompt_template: str | None = None

    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    cost_estimate_usd: float = 0.0
    reliability_score: float = 0.8


class EnableAgentRequest(BaseModel):
    enabled: bool = True
    pinned_version_id: UUID | None = None
    policy: dict[str, Any] = Field(default_factory=dict)


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


@app.get("/personas")
async def list_personas():
    return personas_to_dict()


@app.get("/regulations/stats")
async def regulation_stats(session: AsyncSession = Depends(get_session)):
    """
    Quick visibility endpoint so operators can confirm ingestion is present.
    """
    total = (await session.execute(select(func.count()).select_from(RegulationUnit))).scalar_one()
    by_code = (
        (
            await session.execute(
                select(RegulationUnit.regulation_code, func.count())
                .group_by(RegulationUnit.regulation_code)
                .order_by(func.count().desc())
            )
        )
        .all()
    )
    return {
        "total_units": int(total or 0),
        "by_regulation_code": [{"regulation_code": c, "count": int(n)} for c, n in by_code],
    }


@app.post("/regulations/seed")
async def seed_regulations(session: AsyncSession = Depends(get_session)):
    """
    Dev/demo helper: seed a minimal GDPR corpus into `regulation_units`.

    This is safe to call repeatedly (idempotent upsert).
    """
    return await seed_regulation_units(session=session)


@app.get("/regulations/seed")
async def seed_regulations_get(session: AsyncSession = Depends(get_session)):
    """
    Browser-friendly alias for seeding (GET), since clicking a link can't issue POST.
    """
    return await seed_regulation_units(session=session)


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


# --- Marketplace v1 ---


@app.get("/marketplace/agents")
async def marketplace_list_agents(q: str | None = None, session: AsyncSession = Depends(get_session)):
    query = select(AgentPackage).order_by(AgentPackage.created_at.desc())
    if q:
        query = query.where(AgentPackage.slug.ilike(f"%{q}%") | AgentPackage.name.ilike(f"%{q}%"))
    pkgs = (await session.execute(query)).scalars().all()
    out = []
    for p in pkgs:
        v = (
            (await session.execute(select(AgentVersion).where(AgentVersion.package_id == p.id).order_by(AgentVersion.created_at.desc())))
            .scalars()
            .first()
        )
        out.append(
            {
                "package": {
                    "id": str(p.id),
                    "publisher": p.publisher,
                    "slug": p.slug,
                    "name": p.name,
                    "description": p.description,
                    "categories": p.categories,
                    "tags": p.tags,
                    "created_at": p.created_at.isoformat(),
                },
                "latest_version": (
                    {
                        "id": str(v.id),
                        "version": v.version,
                        "runtime": v.runtime,
                        "status": v.status,
                        "cost_estimate_usd": v.cost_estimate_usd,
                        "reliability_score": v.reliability_score,
                        "run_count": v.run_count,
                        "success_count": v.success_count,
                        "avg_latency_ms": v.avg_latency_ms,
                        "created_at": v.created_at.isoformat(),
                    }
                    if v
                    else None
                ),
            }
        )
    return {"agents": out}


@app.get("/marketplace/agents/{package_id}")
async def marketplace_get_agent(package_id: UUID, session: AsyncSession = Depends(get_session)):
    pkg = (await session.execute(select(AgentPackage).where(AgentPackage.id == package_id))).scalars().first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Agent package not found")
    versions = (
        (await session.execute(select(AgentVersion).where(AgentVersion.package_id == pkg.id).order_by(AgentVersion.created_at.desc())))
        .scalars()
        .all()
    )
    return {
        "package": {
            "id": str(pkg.id),
            "publisher": pkg.publisher,
            "slug": pkg.slug,
            "name": pkg.name,
            "description": pkg.description,
            "categories": pkg.categories,
            "tags": pkg.tags,
            "created_at": pkg.created_at.isoformat(),
        },
        "versions": [
            {
                "id": str(v.id),
                "package_id": str(v.package_id),
                "version": v.version,
                "release_notes": v.release_notes,
                "runtime": v.runtime,
                "builtin_agent_name": v.builtin_agent_name,
                "endpoint_url": v.endpoint_url,
                "prompt_template": v.prompt_template,
                "input_schema": v.input_schema,
                "output_schema": v.output_schema,
                "cost_estimate_usd": v.cost_estimate_usd,
                "reliability_score": v.reliability_score,
                "status": v.status,
                "run_count": v.run_count,
                "success_count": v.success_count,
                "avg_latency_ms": v.avg_latency_ms,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
    }


@app.post("/marketplace/agents/publish")
async def marketplace_publish(req: PublishAgentVersionRequest, session: AsyncSession = Depends(get_session)):
    existing = (await session.execute(select(AgentPackage).where(AgentPackage.slug == req.slug))).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="Agent package already exists")
    pkg = AgentPackage(
        publisher=req.publisher,
        slug=req.slug,
        name=req.name,
        description=req.description,
        categories=req.categories,
        tags=req.tags,
    )
    session.add(pkg)
    await session.commit()
    await session.refresh(pkg)
    ver = AgentVersion(
        package_id=pkg.id,
        version=req.version,
        release_notes=req.release_notes,
        runtime=req.runtime,
        builtin_agent_name=req.builtin_agent_name,
        endpoint_url=req.endpoint_url,
        prompt_template=req.prompt_template,
        input_schema=req.input_schema,
        output_schema=req.output_schema,
        cost_estimate_usd=req.cost_estimate_usd,
        reliability_score=req.reliability_score,
        status="active",
    )
    session.add(ver)
    await session.commit()
    await session.refresh(ver)
    return {"ok": True, "package_id": str(pkg.id), "version_id": str(ver.id)}


@app.post("/marketplace/agents/{package_id}/versions")
async def marketplace_publish_version(package_id: UUID, req: PublishAgentVersionRequest, session: AsyncSession = Depends(get_session)):
    pkg = (await session.execute(select(AgentPackage).where(AgentPackage.id == package_id))).scalars().first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Agent package not found")
    exists = (
        (await session.execute(select(AgentVersion).where(AgentVersion.package_id == package_id).where(AgentVersion.version == req.version)))
        .scalars()
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Version already exists for package")
    ver = AgentVersion(
        package_id=pkg.id,
        version=req.version,
        release_notes=req.release_notes,
        runtime=req.runtime,
        builtin_agent_name=req.builtin_agent_name,
        endpoint_url=req.endpoint_url,
        prompt_template=req.prompt_template,
        input_schema=req.input_schema,
        output_schema=req.output_schema,
        cost_estimate_usd=req.cost_estimate_usd,
        reliability_score=req.reliability_score,
        status="active",
    )
    session.add(ver)
    await session.commit()
    await session.refresh(ver)
    return {"ok": True, "version_id": str(ver.id)}


@app.post("/orgs")
async def create_org(name: str, session: AsyncSession = Depends(get_session)):
    existing = (await session.execute(select(Org).where(Org.name == name))).scalars().first()
    if existing:
        return {"ok": True, "org_id": str(existing.id), "name": existing.name}
    org = Org(name=name)
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return {"ok": True, "org_id": str(org.id), "name": org.name}


@app.get("/orgs/{org_id}/agents")
async def org_list_enabled(org_id: UUID, session: AsyncSession = Depends(get_session)):
    rows = (
        (await session.execute(select(OrgAgentEnablement).where(OrgAgentEnablement.org_id == org_id)))
        .scalars()
        .all()
    )
    return {
        "org_id": str(org_id),
        "enabled": [
            {
                "id": str(r.id),
                "package_id": str(r.package_id),
                "enabled": r.enabled,
                "pinned_version_id": str(r.pinned_version_id) if r.pinned_version_id else None,
                "policy": r.policy,
            }
            for r in rows
        ],
    }


@app.post("/orgs/{org_id}/agents/{package_id}/enable")
async def org_enable_agent(org_id: UUID, package_id: UUID, req: EnableAgentRequest, session: AsyncSession = Depends(get_session)):
    pkg = (await session.execute(select(AgentPackage).where(AgentPackage.id == package_id))).scalars().first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Agent package not found")
    row = (
        (
            await session.execute(
                select(OrgAgentEnablement)
                .where(OrgAgentEnablement.org_id == org_id)
                .where(OrgAgentEnablement.package_id == package_id)
            )
        )
        .scalars()
        .first()
    )
    if row:
        row.enabled = True
        row.pinned_version_id = req.pinned_version_id
        row.policy = req.policy or {}
        await session.merge(row)
        await session.commit()
        return {"ok": True, "enablement_id": str(row.id)}
    row = OrgAgentEnablement(org_id=org_id, package_id=package_id, enabled=True, pinned_version_id=req.pinned_version_id, policy=req.policy or {})
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"ok": True, "enablement_id": str(row.id)}


@app.post("/orgs/{org_id}/agents/{package_id}/disable")
async def org_disable_agent(org_id: UUID, package_id: UUID, session: AsyncSession = Depends(get_session)):
    row = (
        (
            await session.execute(
                select(OrgAgentEnablement)
                .where(OrgAgentEnablement.org_id == org_id)
                .where(OrgAgentEnablement.package_id == package_id)
            )
        )
        .scalars()
        .first()
    )
    if not row:
        return {"ok": True, "disabled": False}
    row.enabled = False
    await session.merge(row)
    await session.commit()
    return {"ok": True, "disabled": True}


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
    org_id = req.org_id or (req.context.get("org_id") if isinstance(req.context, dict) else None)
    if isinstance(req.context, dict) and org_id and "org_id" not in req.context:
        # Ensure orchestrator can see org_id for marketplace selection.
        req.context["org_id"] = str(org_id)
    execution = Execution(org_id=org_id, intent=req.intent, context=req.context, workflow=workflow or "auto", status="queued")
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

