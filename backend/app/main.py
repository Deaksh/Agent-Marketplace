from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
import hashlib
import json
import logging
from uuid import UUID
from uuid import uuid5
from uuid import NAMESPACE_URL
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.builtin.intent_parser import IntentParserAgent
from app.agents.builtin.obligation_mapper import ObligationMapperAgent
from app.agents.builtin.regulation_retriever import RegulationRetrieverAgent
from app.agents.builtin.report_generator import ReportGeneratorAgent
from app.agents.builtin.risk_scorer import RiskScorerAgent
from app.agents.registry import AgentRegistry, spec_to_dict
from app.core.config import settings
from app.auth.jwt import create_access_token, decode_access_token, hash_password, verify_password
from app.db.models import Agent as AgentRow
from app.db.models import (
    AgentPackage,
    AgentVersion,
    AuditLog,
    Execution,
    ExecutionStep,
    Org,
    OrgAgentEnablement,
    OrgPolicy,
    Outcome,
    RegulationUnit,
    ComplianceCase,
    Membership,
    User,
)
from app.db.session import get_session, init_db
from app.orchestrator.orchestrator import Orchestrator
from app.retrieval.regulations import RegulationRetriever
from app.validator.validator import OutcomeValidator
from app.ingestion.seed_marketplace import seed_marketplace_packages
from app.ingestion.seed_regulations import seed_regulation_units
from app.ingestion.eurlex_ai_act import ingest_eu_ai_act_from_eurlex
from app.ingestion.control_pack import ControlPackUnit, ingest_control_pack
from app.ingestion.reembed import reembed_all_regulation_units
from app.personas import personas_to_dict
from app.export.case_export import build_case_export, render_case_export_pdf
from app.observability.logging import configure_logging


logger = logging.getLogger("oel")


class ExecuteRequest(BaseModel):
    intent: str = Field(..., min_length=3)
    context: dict[str, Any] = Field(default_factory=dict)
    workflow: str | None = None
    org_id: UUID | None = None
    idempotency_key: str | None = None


class ExecuteResponse(BaseModel):
    execution_id: UUID
    status: str
    # Decision-first (enterprise) fields
    decision: str | None = None  # COMPLIANT|NON_COMPLIANT|NEEDS_REVIEW
    severity: str | None = None  # LOW|MEDIUM|HIGH|CRITICAL
    blocking_issues: list[dict[str, Any]] | None = None
    required_actions: list[dict[str, Any]] | None = None
    citations: list[dict[str, Any]] | None = None

    # Legacy fields (kept for backward compatibility)
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


class UpdateOrgPolicyRequest(BaseModel):
    allowed_packages: list[str] = Field(default_factory=list)
    blocked_packages: list[str] = Field(default_factory=list)


class ControlPackIngestRequest(BaseModel):
    framework_code: str
    publisher: str = "customer"
    version: str = "uploaded"
    source_url: str | None = None
    source_doc_id: str | None = None
    jurisdiction: str | None = None
    units: list[dict[str, Any]] = Field(default_factory=list)


class CreateCaseRequest(BaseModel):
    title: str = Field(..., min_length=3)
    description: str = ""
    owner_id: str | None = None
    org_id: UUID | None = None


class CaseTransitionRequest(BaseModel):
    status: str = Field(..., min_length=2)  # DRAFT|IN_REVIEW|APPROVED|REJECTED
    final_decision: dict[str, Any] | None = None


class CaseResponse(BaseModel):
    case_id: UUID
    title: str
    description: str
    owner_id: str | None
    org_id: UUID | None
    status: str
    final_decision: dict[str, Any] | None = None
    linked_executions: list[UUID] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    finalized_at: str | None = None


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    org_name: str = Field(default="default", min_length=1)


class LoginRequest(BaseModel):
    email: str
    password: str


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def require_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        claims = decode_access_token(token)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid token")
    u = (await session.execute(select(User).where(User.id == UUID(claims.sub)))).scalars().first()
    if not u:
        raise HTTPException(status_code=401, detail="Unknown user")
    return u


async def require_org_context(
    user: User = Depends(require_user),
    x_org_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> UUID:
    memberships = (await session.execute(select(Membership).where(Membership.user_id == user.id))).scalars().all()
    if not memberships:
        raise HTTPException(status_code=403, detail="User has no org memberships")
    if x_org_id:
        try:
            oid = UUID(x_org_id)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid X-Org-Id")
        if not any(m.org_id == oid for m in memberships):
            raise HTTPException(status_code=403, detail="Not a member of org")
        return oid
    return memberships[0].org_id


async def require_admin_org(
    user: User = Depends(require_user),
    org_id: UUID = Depends(require_org_context),
    session: AsyncSession = Depends(get_session),
) -> UUID:
    m = (
        (await session.execute(select(Membership).where(Membership.user_id == user.id).where(Membership.org_id == org_id)))
        .scalars()
        .first()
    )
    if not m or m.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return org_id


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
    configure_logging()
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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id") or str(uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics/agents")
async def agent_metrics(session: AsyncSession = Depends(get_session)):
    """
    Minimal step-level metrics endpoint (MVP observability).
    """
    # Marketplace versions already track aggregate counters/latency.
    versions = (await session.execute(select(AgentVersion).order_by(AgentVersion.created_at.desc()))).scalars().all()
    ver_payload = [
        {
            "version_id": str(v.id),
            "package_id": str(v.package_id),
            "version": v.version,
            "runtime": v.runtime,
            "cert_status": getattr(v, "cert_status", None),
            "run_count": v.run_count,
            "success_count": v.success_count,
            "success_rate": (float(v.success_count) / float(v.run_count)) if v.run_count else None,
            "avg_latency_ms": v.avg_latency_ms,
        }
        for v in versions[:200]
    ]

    # Builtin and overall step metrics (derived from ExecutionStep).
    steps = (await session.execute(select(ExecutionStep))).scalars().all()
    by_agent: dict[str, dict[str, float]] = {}
    for s in steps:
        a = s.agent_name
        row = by_agent.setdefault(a, {"runs": 0.0, "success": 0.0, "failed": 0.0, "retries": 0.0, "lat_ms_sum": 0.0, "lat_ms_n": 0.0})
        row["runs"] += 1.0
        st = (s.status or "").upper()
        if st == "SUCCESS":
            row["success"] += 1.0
        if st == "FAILED":
            row["failed"] += 1.0
        if st == "RETRIED":
            row["retries"] += 1.0
        if s.started_at and s.completed_at:
            row["lat_ms_sum"] += (s.completed_at - s.started_at).total_seconds() * 1000.0
            row["lat_ms_n"] += 1.0

    builtin_payload = []
    for agent, row in sorted(by_agent.items(), key=lambda kv: kv[0]):
        runs = row["runs"]
        lat_n = row["lat_ms_n"] or 0.0
        builtin_payload.append(
            {
                "agent": agent,
                "runs": int(runs),
                "success": int(row["success"]),
                "failed": int(row["failed"]),
                "retries": int(row["retries"]),
                "success_rate": (row["success"] / runs) if runs else None,
                "avg_latency_ms": (row["lat_ms_sum"] / lat_n) if lat_n else None,
            }
        )

    return {"marketplace_versions": ver_payload, "steps_by_agent": builtin_payload}


@app.get("/personas")
async def list_personas():
    return personas_to_dict()


@app.post("/auth/register")
async def auth_register(req: RegisterRequest, session: AsyncSession = Depends(get_session)):
    email = req.email.strip().lower()
    existing = (await session.execute(select(User).where(User.email == email))).scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=email, password_hash=hash_password(req.password))
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # Create or reuse org, and grant admin membership.
    org = (await session.execute(select(Org).where(Org.name == req.org_name))).scalars().first()
    if not org:
        org = Org(name=req.org_name)
        session.add(org)
        await session.commit()
        await session.refresh(org)

    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    await session.commit()

    token = create_access_token(sub=str(user.id), email=user.email)
    return {"access_token": token, "token_type": "bearer", "user_id": str(user.id), "org_id": str(org.id)}


@app.post("/auth/login")
async def auth_login(req: LoginRequest, session: AsyncSession = Depends(get_session)):
    email = req.email.strip().lower()
    user = (await session.execute(select(User).where(User.email == email))).scalars().first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    org_id = (await session.execute(select(Membership.org_id).where(Membership.user_id == user.id))).scalars().first()
    token = create_access_token(sub=str(user.id), email=user.email)
    return {"access_token": token, "token_type": "bearer", "user_id": str(user.id), "org_id": str(org_id) if org_id else None}


@app.get("/me")
async def me(user: User = Depends(require_user), session: AsyncSession = Depends(get_session)):
    memberships = (await session.execute(select(Membership).where(Membership.user_id == user.id))).scalars().all()
    return {
        "user": {"id": str(user.id), "email": user.email},
        "memberships": [{"org_id": str(m.org_id), "role": m.role} for m in memberships],
    }


@app.post("/cases", response_model=CaseResponse)
async def create_case(
    req: CreateCaseRequest,
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    c = ComplianceCase(
        title=req.title,
        description=req.description or "",
        owner_id=req.owner_id or str(user.id),
        org_id=org_id,
        status="DRAFT",
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return CaseResponse(
        case_id=c.id,
        title=c.title,
        description=c.description,
        owner_id=c.owner_id,
        org_id=c.org_id,
        status=c.status,
        final_decision=c.final_decision,
        linked_executions=[],
        created_at=c.created_at.isoformat() if c.created_at else None,
        updated_at=c.updated_at.isoformat() if c.updated_at else None,
        finalized_at=c.finalized_at.isoformat() if c.finalized_at else None,
    )


@app.get("/cases")
async def list_cases(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    org_id: UUID = Depends(require_org_context),
    session: AsyncSession = Depends(get_session),
):
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    q = select(ComplianceCase)
    if status:
        q = q.where(ComplianceCase.status == status)
    q = q.where(ComplianceCase.org_id == org_id)
    q = q.order_by(ComplianceCase.updated_at.desc()).offset(offset).limit(limit)
    rows = (await session.execute(q)).scalars().all()

    ids = [r.id for r in rows]
    ex_rows = (
        (await session.execute(select(Execution.case_id, Execution.id).where(Execution.case_id.in_(ids))))  # type: ignore[arg-type]
        .all()
        if ids
        else []
    )
    ex_by_case: dict[UUID, list[UUID]] = {}
    for cid, eid in ex_rows:
        if cid and eid:
            ex_by_case.setdefault(cid, []).append(eid)

    return {
        "limit": limit,
        "offset": offset,
        "cases": [
            CaseResponse(
                case_id=r.id,
                title=r.title,
                description=r.description,
                owner_id=r.owner_id,
                org_id=r.org_id,
                status=r.status,
                final_decision=r.final_decision,
                linked_executions=ex_by_case.get(r.id, []),
                created_at=r.created_at.isoformat() if r.created_at else None,
                updated_at=r.updated_at.isoformat() if r.updated_at else None,
                finalized_at=r.finalized_at.isoformat() if r.finalized_at else None,
            ).model_dump()
            for r in rows
        ],
    }


@app.get("/cases/{case_id}", response_model=CaseResponse)
async def get_case(case_id: UUID, org_id: UUID = Depends(require_org_context), session: AsyncSession = Depends(get_session)):
    c = (await session.execute(select(ComplianceCase).where(ComplianceCase.id == case_id))).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Case not found")
    if c.org_id != org_id:
        raise HTTPException(status_code=404, detail="Case not found")

    ex_ids = (
        (await session.execute(select(Execution.id).where(Execution.case_id == case_id).order_by(Execution.created_at.desc())))
        .scalars()
        .all()
    )
    return CaseResponse(
        case_id=c.id,
        title=c.title,
        description=c.description,
        owner_id=c.owner_id,
        org_id=c.org_id,
        status=c.status,
        final_decision=c.final_decision,
        linked_executions=ex_ids,
        created_at=c.created_at.isoformat() if c.created_at else None,
        updated_at=c.updated_at.isoformat() if c.updated_at else None,
        finalized_at=c.finalized_at.isoformat() if c.finalized_at else None,
    )


@app.post("/cases/{case_id}/transition", response_model=CaseResponse)
async def transition_case(
    case_id: UUID,
    req: CaseTransitionRequest,
    org_id: UUID = Depends(require_org_context),
    session: AsyncSession = Depends(get_session),
):
    c = (await session.execute(select(ComplianceCase).where(ComplianceCase.id == case_id))).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Case not found")
    if c.org_id != org_id:
        raise HTTPException(status_code=404, detail="Case not found")

    new_status = req.status.strip().upper()
    if new_status not in {"DRAFT", "IN_REVIEW", "APPROVED", "REJECTED"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    c.status = new_status
    c.updated_at = datetime.utcnow()
    if new_status in {"APPROVED", "REJECTED"}:
        c.finalized_at = datetime.utcnow()
        if req.final_decision is not None:
            c.final_decision = req.final_decision
    await session.merge(c)
    await session.commit()

    ex_ids = (
        (await session.execute(select(Execution.id).where(Execution.case_id == case_id).order_by(Execution.created_at.desc())))
        .scalars()
        .all()
    )
    return CaseResponse(
        case_id=c.id,
        title=c.title,
        description=c.description,
        owner_id=c.owner_id,
        org_id=c.org_id,
        status=c.status,
        final_decision=c.final_decision,
        linked_executions=ex_ids,
        created_at=c.created_at.isoformat() if c.created_at else None,
        updated_at=c.updated_at.isoformat() if c.updated_at else None,
        finalized_at=c.finalized_at.isoformat() if c.finalized_at else None,
    )


@app.get("/cases/{case_id}/export")
async def export_case(
    case_id: UUID,
    format: str | None = None,
    org_id: UUID = Depends(require_org_context),
    session: AsyncSession = Depends(get_session),
):
    c = (await session.execute(select(ComplianceCase).where(ComplianceCase.id == case_id))).scalars().first()
    if not c or c.org_id != org_id:
        raise HTTPException(status_code=404, detail="Case not found")

    export = await build_case_export(session=session, case_id=case_id)
    fmt = (format or "json").lower().strip()
    if fmt == "pdf":
        pdf_bytes = render_case_export_pdf(export=export)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"content-disposition": f'attachment; filename=\"case-{case_id}.pdf\"'},
        )
    return export


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


@app.get("/regulations/units")
async def list_regulation_units(
    regulation_code: str | None = None,
    framework_code: str | None = None,
    q: str | None = None,
    jurisdiction: str | None = None,
    effective_at: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    query = select(RegulationUnit)
    if regulation_code:
        query = query.where(RegulationUnit.regulation_code == regulation_code)
    if framework_code:
        query = query.where(RegulationUnit.framework_code == framework_code)
    if jurisdiction:
        query = query.where(RegulationUnit.jurisdiction == jurisdiction)
    if effective_at:
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(effective_at)
            query = query.where(or_(RegulationUnit.effective_from.is_(None), RegulationUnit.effective_from <= dt))
            query = query.where(or_(RegulationUnit.effective_to.is_(None), RegulationUnit.effective_to >= dt))
        except Exception:  # noqa: BLE001
            pass
    if q:
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                RegulationUnit.unit_id.ilike(needle),
                RegulationUnit.title.ilike(needle),
                RegulationUnit.text.ilike(needle),
            )
        )
    query = query.order_by(RegulationUnit.regulation_code.asc(), RegulationUnit.unit_id.asc()).offset(offset).limit(limit)
    rows = (await session.execute(query)).scalars().all()
    return {
        "limit": limit,
        "offset": offset,
        "units": [
            {
                "id": r.id,
                "regulation_code": r.regulation_code,
                "framework_code": r.framework_code,
                "unit_id": r.unit_id,
                "title": r.title,
                "version": r.version,
                "text": r.text,
                "meta": r.meta,
                "jurisdiction": r.jurisdiction,
                "effective_from": r.effective_from.isoformat() if r.effective_from else None,
                "effective_to": r.effective_to.isoformat() if r.effective_to else None,
                "source_url": r.source_url,
                "source_doc_id": r.source_doc_id,
            }
            for r in rows
        ],
    }


@app.get("/regulations/units/{unit_pk}")
async def get_regulation_unit(unit_pk: int, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(select(RegulationUnit).where(RegulationUnit.id == unit_pk))).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Regulation unit not found")
    return {
        "unit": {
            "id": row.id,
            "regulation_code": row.regulation_code,
            "unit_id": row.unit_id,
            "title": row.title,
            "version": row.version,
            "text": row.text,
            "meta": row.meta,
        }
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


@app.post("/regulations/ingest/eu_ai_act")
async def ingest_eu_ai_act(url: str | None = None, session: AsyncSession = Depends(get_session)):
    """
    Authoritative ingestion (best-effort) from EUR-Lex ELI URL.
    """
    return await ingest_eu_ai_act_from_eurlex(session=session, url=(url or None) or "https://eur-lex.europa.eu/eli/reg/2024/1689/oj")


@app.post("/regulations/ingest/control_pack")
async def ingest_control_pack_endpoint(req: ControlPackIngestRequest, session: AsyncSession = Depends(get_session)):
    """
    Licensing-safe ingestion endpoint for SOC2 / ISO27001 (customer-provided packs).
    """
    framework = (req.framework_code or "").strip().upper()
    if not framework:
        raise HTTPException(status_code=400, detail="framework_code required")
    units: list[ControlPackUnit] = []
    for u in req.units:
        if not isinstance(u, dict):
            continue
        unit_id = str(u.get("unit_id") or "").strip()
        if not unit_id:
            continue
        units.append(
            ControlPackUnit(
                framework_code=framework,
                unit_id=unit_id,
                title=str(u.get("title") or ""),
                text=str(u.get("text") or ""),
                jurisdiction=req.jurisdiction,
                source_url=req.source_url,
                source_doc_id=req.source_doc_id,
                version=req.version,
                meta=(u.get("meta") if isinstance(u.get("meta"), dict) else None),
            )
        )

    out = await ingest_control_pack(session=session, units=units, publisher=req.publisher)
    out["framework_code"] = framework
    return out


@app.post("/regulations/ingest/reembed")
async def reembed_regulations(
    framework_code: str | None = Query(default=None, description="If set, only rows with this framework_code."),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=50_000,
        description="Optional cap on rows processed (ordered by id).",
    ),
    session: AsyncSession = Depends(get_session),
):
    """
    Recompute embeddings for regulation units (e.g. after setting `HF_TOKEN`).

    Loads `.env` from `backend/.env` or the repo-root `.env` (not `.env.example`).
    """
    return await reembed_all_regulation_units(session=session, framework_code=framework_code, limit=limit)


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


@app.post("/marketplace/seed")
async def marketplace_seed(session: AsyncSession = Depends(get_session)):
    """Dev/demo: idempotent seed of example marketplace packages (built-in agents as listings)."""
    return await seed_marketplace_packages(session=session)


@app.get("/marketplace/seed")
async def marketplace_seed_get(session: AsyncSession = Depends(get_session)):
    """Browser-friendly alias for seeding marketplace demo packages (GET)."""
    return await seed_marketplace_packages(session=session)


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


@app.get("/orgs/{org_id}/policy")
async def org_get_policy(org_id: UUID, admin_org_id: UUID = Depends(require_admin_org), session: AsyncSession = Depends(get_session)):
    if org_id != admin_org_id:
        raise HTTPException(status_code=404, detail="Org not found")
    row = (await session.execute(select(OrgPolicy).where(OrgPolicy.org_id == org_id))).scalars().first()
    if not row:
        return {"org_id": str(org_id), "allowed_packages": [], "blocked_packages": []}
    return {"org_id": str(org_id), "allowed_packages": row.allowed_packages, "blocked_packages": row.blocked_packages}


@app.post("/orgs/{org_id}/policy")
async def org_set_policy(org_id: UUID, req: UpdateOrgPolicyRequest, admin_org_id: UUID = Depends(require_admin_org), session: AsyncSession = Depends(get_session)):
    if org_id != admin_org_id:
        raise HTTPException(status_code=404, detail="Org not found")
    row = (await session.execute(select(OrgPolicy).where(OrgPolicy.org_id == org_id))).scalars().first()
    allowed = [str(x) for x in (req.allowed_packages or []) if str(x).strip()]
    blocked = [str(x) for x in (req.blocked_packages or []) if str(x).strip()]
    if row:
        row.allowed_packages = allowed
        row.blocked_packages = blocked
        row.updated_at = datetime.utcnow()
        await session.merge(row)
        await session.commit()
        return {"ok": True, "policy_id": str(row.id)}
    row = OrgPolicy(org_id=org_id, allowed_packages=allowed, blocked_packages=blocked)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"ok": True, "policy_id": str(row.id)}


@app.post("/orgs/{org_id}/agents/{package_id}/enable")
async def org_enable_agent(
    org_id: UUID,
    package_id: UUID,
    req: EnableAgentRequest,
    admin_org_id: UUID = Depends(require_admin_org),
    session: AsyncSession = Depends(get_session),
):
    if org_id != admin_org_id:
        raise HTTPException(status_code=404, detail="Org not found")
    pkg = (await session.execute(select(AgentPackage).where(AgentPackage.id == package_id))).scalars().first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Agent package not found")

    if req.pinned_version_id:
        ver = (await session.execute(select(AgentVersion).where(AgentVersion.id == req.pinned_version_id))).scalars().first()
        if not ver:
            raise HTTPException(status_code=404, detail="Pinned agent version not found")
        if ver.package_id != package_id:
            raise HTTPException(status_code=400, detail="Pinned version does not belong to package")
        if ver.status != "active":
            raise HTTPException(status_code=400, detail="Pinned version is not active")
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
async def org_disable_agent(org_id: UUID, package_id: UUID, admin_org_id: UUID = Depends(require_admin_org), session: AsyncSession = Depends(get_session)):
    if org_id != admin_org_id:
        raise HTTPException(status_code=404, detail="Org not found")
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

    idem = (req.idempotency_key or (req.context.get("idempotency_key") if isinstance(req.context, dict) else None) or "").strip()
    if idem:
        # If an execution already exists for this org+key, return it (idempotent create).
        existing = (
            (
                await session.execute(
                    select(Execution).where(Execution.org_id == org_id).where(Execution.idempotency_key == idem)  # type: ignore[arg-type]
                )
            )
            .scalars()
            .first()
        )
        if existing:
            return ExecuteResponse(execution_id=existing.id, status=existing.status)

    execution_kwargs: dict[str, Any] = {
        "idempotency_key": (idem or None),
        "org_id": org_id,
        "intent": req.intent,
        "context": req.context,
        "workflow": workflow or "auto",
        "status": "queued",
    }
    if idem:
        execution_kwargs["id"] = uuid5(NAMESPACE_URL, f"oel:{idem}")
    execution = Execution(**execution_kwargs)
    session.add(execution)
    await session.commit()
    await session.refresh(execution)

    # Async-ready execution: run in background task for MVP.
    background.add_task(_run_execution, execution_id=execution.id)

    return ExecuteResponse(execution_id=execution.id, status="queued")


@app.post("/cases/{case_id}/execute", response_model=ExecuteResponse)
async def execute_case(
    case_id: UUID,
    req: ExecuteRequest,
    background: BackgroundTasks,
    org_id: UUID = Depends(require_org_context),
    session: AsyncSession = Depends(get_session),
):
    case = (await session.execute(select(ComplianceCase).where(ComplianceCase.id == case_id))).scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.org_id != org_id:
        raise HTTPException(status_code=404, detail="Case not found")

    workflow = (req.workflow or req.context.get("workflow") or "auto").strip() if isinstance(req.context, dict) else (req.workflow or "auto")
    if isinstance(req.context, dict):
        req.context["case_id"] = str(case_id)
        if org_id and "org_id" not in req.context:
            req.context["org_id"] = str(org_id)

    idem = (req.idempotency_key or (req.context.get("idempotency_key") if isinstance(req.context, dict) else None) or "").strip()
    if not idem:
        idem_payload = {
            "case_id": str(case_id),
            "org_id": str(org_id) if org_id else None,
            "workflow": workflow or "auto",
            "intent": req.intent,
            "context": req.context,
        }
        idem = "caseexec:" + hashlib.sha256(json.dumps(idem_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:32]
        if isinstance(req.context, dict):
            req.context["idempotency_key"] = idem

    existing = (
        (
            await session.execute(
                select(Execution)
                .where(Execution.case_id == case_id)
                .where(Execution.idempotency_key == idem)  # type: ignore[arg-type]
            )
        )
        .scalars()
        .first()
    )
    if existing:
        return ExecuteResponse(execution_id=existing.id, status=existing.status)

    execution = Execution(
        id=uuid5(NAMESPACE_URL, f"oel:{idem}"),
        idempotency_key=idem,
        org_id=org_id,
        case_id=case_id,
        intent=req.intent,
        context=req.context,
        workflow=workflow or "auto",
        status="queued",
    )
    session.add(execution)
    await session.commit()
    await session.refresh(execution)

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
    decision_payload = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    return ExecuteResponse(
        execution_id=execution.id,
        status=execution.status,
        decision=decision_payload.get("decision"),
        severity=decision_payload.get("severity"),
        blocking_issues=decision_payload.get("blocking_issues"),
        required_actions=decision_payload.get("required_actions"),
        citations=decision_payload.get("citations"),
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
    pkg_ids = {r.agent_package_id for r in rows if r.agent_package_id}
    ver_ids = {r.agent_version_id for r in rows if r.agent_version_id}
    packages = (
        (await session.execute(select(AgentPackage).where(AgentPackage.id.in_(pkg_ids))))  # type: ignore[arg-type]
        .scalars()
        .all()
        if pkg_ids
        else []
    )
    versions = (
        (await session.execute(select(AgentVersion).where(AgentVersion.id.in_(ver_ids))))  # type: ignore[arg-type]
        .scalars()
        .all()
        if ver_ids
        else []
    )
    pkg_by_id = {p.id: p for p in packages}
    ver_by_id = {v.id: v for v in versions}
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
                "agent_package_id": str(r.agent_package_id) if r.agent_package_id else None,
                "agent_version_id": str(r.agent_version_id) if r.agent_version_id else None,
                "agent_package": (
                    {
                        "id": str(pkg_by_id[r.agent_package_id].id),
                        "publisher": pkg_by_id[r.agent_package_id].publisher,
                        "slug": pkg_by_id[r.agent_package_id].slug,
                        "name": pkg_by_id[r.agent_package_id].name,
                    }
                    if r.agent_package_id and r.agent_package_id in pkg_by_id
                    else None
                ),
                "agent_version": (
                    {
                        "id": str(ver_by_id[r.agent_version_id].id),
                        "version": ver_by_id[r.agent_version_id].version,
                        "runtime": ver_by_id[r.agent_version_id].runtime,
                        "builtin_agent_name": ver_by_id[r.agent_version_id].builtin_agent_name,
                    }
                    if r.agent_version_id and r.agent_version_id in ver_by_id
                    else None
                ),
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


@app.get("/executions/{execution_id}/timeline")
async def execution_timeline(execution_id: UUID, session: AsyncSession = Depends(get_session)):
    execution = (await session.execute(select(Execution).where(Execution.id == execution_id))).scalars().first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    steps = (
        (await session.execute(select(ExecutionStep).where(ExecutionStep.execution_id == execution_id).order_by(ExecutionStep.step_index)))
        .scalars()
        .all()
    )
    audit = (
        (await session.execute(select(AuditLog).where(AuditLog.execution_id == execution_id).order_by(AuditLog.created_at)))
        .scalars()
        .all()
    )

    events: list[dict[str, Any]] = []
    for s in steps:
        if s.started_at:
            events.append(
                {
                    "ts": s.started_at.isoformat(),
                    "kind": "step.started_at",
                    "step_id": str(s.id),
                    "step_index": s.step_index,
                    "agent": s.agent_name,
                }
            )
        if s.completed_at:
            latency_ms = (s.completed_at - s.started_at).total_seconds() * 1000.0 if s.started_at else None
            events.append(
                {
                    "ts": s.completed_at.isoformat(),
                    "kind": "step.completed_at",
                    "step_id": str(s.id),
                    "step_index": s.step_index,
                    "agent": s.agent_name,
                    "status": s.status,
                    "attempts": s.attempts,
                    "latency_ms": latency_ms,
                    "error": s.error,
                }
            )

    for a in audit:
        events.append(
            {
                "ts": a.created_at.isoformat() if a.created_at else None,
                "kind": "audit",
                "event_type": a.event_type,
                "message": a.message,
                "step_id": str(a.step_id) if a.step_id else None,
                "payload": a.payload,
            }
        )

    def _ts(e: dict[str, Any]) -> str:
        return str(e.get("ts") or "")

    events_sorted = sorted([e for e in events if e.get("ts")], key=_ts)

    latency_ms = None
    if execution.started_at and execution.completed_at:
        latency_ms = (execution.completed_at - execution.started_at).total_seconds() * 1000.0

    return {
        "execution_id": str(execution_id),
        "status": execution.status,
        "created_at": execution.created_at.isoformat() if execution.created_at else None,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "latency_ms": latency_ms,
        "steps": [
            {
                "id": str(s.id),
                "step_index": s.step_index,
                "agent": s.agent_name,
                "status": s.status,
                "attempts": s.attempts,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "error": s.error,
            }
            for s in steps
        ],
        "events": events_sorted,
    }

