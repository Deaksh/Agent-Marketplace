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
        await conn.run_sync(SQLModel.metadata.create_all)
        # Lightweight SQLite schema evolution for MVP (avoids introducing Alembic yet).
        # Ensures new nullable columns exist on existing tables in dev/codespaces.
        if settings.database_url.startswith("sqlite"):
            # Execution.org_id
            cols = (await conn.execute(text("PRAGMA table_info(execution)"))).all()
            existing = {c[1] for c in cols}  # type: ignore[index]
            if "org_id" not in existing:
                await conn.execute(text("ALTER TABLE execution ADD COLUMN org_id VARCHAR"))

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


async def get_session():
    async with async_session_factory() as session:
        yield session

