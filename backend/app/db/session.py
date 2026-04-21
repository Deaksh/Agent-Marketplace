from __future__ import annotations

from sqlalchemy import text
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        # Postgres bootstrap for pgvector.
        if settings.database_url.startswith("postgres"):
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(SQLModel.metadata.create_all)
        # Lightweight SQLite schema evolution for MVP (avoids introducing Alembic yet).
        # Ensures new nullable columns exist on existing tables in dev/codespaces.
        if settings.database_url.startswith("sqlite"):
            # ComplianceCase intake + decision fields
            cols = (await conn.execute(text("PRAGMA table_info(compliancecase)"))).all()
            existing = {c[1] for c in cols}  # type: ignore[index]
            alters: list[str] = []
            if "system_name" not in existing:
                alters.append("ALTER TABLE compliancecase ADD COLUMN system_name VARCHAR")
            if "system_description" not in existing:
                alters.append("ALTER TABLE compliancecase ADD COLUMN system_description VARCHAR")
            if "use_case_type" not in existing:
                alters.append("ALTER TABLE compliancecase ADD COLUMN use_case_type VARCHAR")
            if "deployment_region" not in existing:
                alters.append("ALTER TABLE compliancecase ADD COLUMN deployment_region VARCHAR")
            if "data_types" not in existing:
                alters.append("ALTER TABLE compliancecase ADD COLUMN data_types JSON")
            if "reviewer_ids" not in existing:
                alters.append("ALTER TABLE compliancecase ADD COLUMN reviewer_ids JSON")
            if "decision_status" not in existing:
                alters.append("ALTER TABLE compliancecase ADD COLUMN decision_status VARCHAR")
            for stmt in alters:
                await conn.execute(text(stmt))

            # Execution.org_id
            cols = (await conn.execute(text("PRAGMA table_info(execution)"))).all()
            existing = {c[1] for c in cols}  # type: ignore[index]
            if "org_id" not in existing:
                await conn.execute(text("ALTER TABLE execution ADD COLUMN org_id VARCHAR"))
            if "idempotency_key" not in existing:
                await conn.execute(text("ALTER TABLE execution ADD COLUMN idempotency_key VARCHAR"))
            if "started_at" not in existing:
                await conn.execute(text("ALTER TABLE execution ADD COLUMN started_at DATETIME"))
            if "case_id" not in existing:
                await conn.execute(text("ALTER TABLE execution ADD COLUMN case_id VARCHAR"))

            cols = (await conn.execute(text("PRAGMA table_info(executionstep)"))).all()
            existing = {c[1] for c in cols}  # type: ignore[index]
            alters: list[str] = []
            if "agent_package_id" not in existing:
                alters.append("ALTER TABLE executionstep ADD COLUMN agent_package_id VARCHAR")
            if "agent_version_id" not in existing:
                alters.append("ALTER TABLE executionstep ADD COLUMN agent_version_id VARCHAR")
            if "cost_usd_estimated" not in existing:
                alters.append("ALTER TABLE executionstep ADD COLUMN cost_usd_estimated FLOAT")
            if "cost_usd_actual" not in existing:
                alters.append("ALTER TABLE executionstep ADD COLUMN cost_usd_actual FLOAT")
            for stmt in alters:
                await conn.execute(text(stmt))

            # AuditLog new linkage fields
            cols = (await conn.execute(text("PRAGMA table_info(auditlog)"))).all()
            existing = {c[1] for c in cols}  # type: ignore[index]
            alters = []
            if "case_id" not in existing:
                alters.append("ALTER TABLE auditlog ADD COLUMN case_id VARCHAR")
            if "org_id" not in existing:
                alters.append("ALTER TABLE auditlog ADD COLUMN org_id VARCHAR")
            if "user_id" not in existing:
                alters.append("ALTER TABLE auditlog ADD COLUMN user_id VARCHAR")
            for stmt in alters:
                await conn.execute(text(stmt))

            # Outcome decision-first columns
            cols = (await conn.execute(text("PRAGMA table_info(outcome)"))).all()
            existing = {c[1] for c in cols}  # type: ignore[index]
            alters = []
            if "decision" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN decision VARCHAR")
            if "severity" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN severity VARCHAR")
            if "risk_score" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN risk_score FLOAT")
            if "decision_version" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN decision_version VARCHAR")
            if "decision_generated_at" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN decision_generated_at DATETIME")
            if "decision_blocking_issues" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN decision_blocking_issues JSON")
            if "decision_required_actions" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN decision_required_actions JSON")
            if "decision_risks" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN decision_risks JSON")
            if "decision_recommendations" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN decision_recommendations JSON")
            if "decision_citations" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN decision_citations JSON")
            if "decision_explainability" not in existing:
                alters.append("ALTER TABLE outcome ADD COLUMN decision_explainability JSON")
            for stmt in alters:
                await conn.execute(text(stmt))

            # API key tables may not exist in older DBs; create_all above should create them,
            # but if the DB existed before the models were introduced, ensure they're present.
            await conn.run_sync(SQLModel.metadata.create_all)

            # AgentVersion.cert_status
            cols = (await conn.execute(text("PRAGMA table_info(agentversion)"))).all()
            existing = {c[1] for c in cols}  # type: ignore[index]
            if "cert_status" not in existing:
                await conn.execute(text("ALTER TABLE agentversion ADD COLUMN cert_status VARCHAR"))

            # regulation_units new fields (keep nullable for incremental adoption)
            cols = (await conn.execute(text("PRAGMA table_info(regulation_units)"))).all()
            existing = {c[1] for c in cols}  # type: ignore[index]
            alters = []
            if "framework_code" not in existing:
                alters.append("ALTER TABLE regulation_units ADD COLUMN framework_code VARCHAR")
            if "jurisdiction" not in existing:
                alters.append("ALTER TABLE regulation_units ADD COLUMN jurisdiction VARCHAR")
            if "effective_from" not in existing:
                alters.append("ALTER TABLE regulation_units ADD COLUMN effective_from DATETIME")
            if "effective_to" not in existing:
                alters.append("ALTER TABLE regulation_units ADD COLUMN effective_to DATETIME")
            if "source_url" not in existing:
                alters.append("ALTER TABLE regulation_units ADD COLUMN source_url VARCHAR")
            if "source_doc_id" not in existing:
                alters.append("ALTER TABLE regulation_units ADD COLUMN source_doc_id VARCHAR")
            if "embedding" not in existing:
                alters.append("ALTER TABLE regulation_units ADD COLUMN embedding JSON")
            for stmt in alters:
                await conn.execute(text(stmt))


async def get_session():
    async with async_session_factory() as session:
        yield session

