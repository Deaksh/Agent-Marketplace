from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RegulationUnit
from app.retrieval.embedder import ConfigurableEmbedder


@dataclass(frozen=True)
class ControlPackUnit:
    framework_code: str  # SOC2 | ISO27001 | ...
    unit_id: str  # CC7.2 | A.5.1 | ...
    title: str
    text: str
    jurisdiction: str | None = None
    source_url: str | None = None
    source_doc_id: str | None = None
    version: str = "uploaded"
    meta: dict[str, Any] | None = None


async def ingest_control_pack(
    *,
    session: AsyncSession,
    units: list[ControlPackUnit],
    publisher: str,
) -> dict[str, Any]:
    """
    Ingest a user-provided control/regulation pack.

    This is the preferred path for SOC2 / ISO where full text may be licensed.
    Users can upload:
    - short summaries
    - their internal control mappings
    - permitted excerpts
    """
    embedder = ConfigurableEmbedder()
    inserted = 0
    updated = 0
    embedded = 0

    for u in units:
        code = (u.framework_code or "").strip().upper()
        if not code:
            continue
        unit_id = (u.unit_id or "").strip()
        if not unit_id:
            continue

        meta = dict(u.meta or {})
        meta.setdefault("publisher", publisher)
        meta.setdefault("ingested_at", datetime.utcnow().isoformat())
        meta.setdefault("citation", {"type": "control", "id": unit_id})

        text_for_embedding = (u.title + "\n" + u.text).strip()
        emb: list[float] | None = None
        if text_for_embedding:
            try:
                emb = (await embedder.embed(text=text_for_embedding)).vector
            except Exception:  # noqa: BLE001
                emb = None

        existing = (
            (
                await session.execute(
                    select(RegulationUnit)
                    .where(RegulationUnit.regulation_code == code)
                    .where(RegulationUnit.framework_code == code)
                    .where(RegulationUnit.unit_id == unit_id)
                )
            )
            .scalars()
            .first()
        )
        if existing:
            existing.title = u.title
            existing.text = u.text
            existing.version = u.version
            existing.meta = meta
            existing.framework_code = code
            existing.jurisdiction = u.jurisdiction
            existing.source_url = u.source_url
            existing.source_doc_id = u.source_doc_id
            if emb:
                existing.embedding = emb
                embedded += 1
            await session.merge(existing)
            updated += 1
        else:
            session.add(
                RegulationUnit(
                    regulation_code=code,
                    framework_code=code,
                    unit_id=unit_id,
                    title=u.title or "",
                    text=u.text or "",
                    version=u.version,
                    meta=meta,
                    jurisdiction=u.jurisdiction,
                    source_url=u.source_url,
                    source_doc_id=u.source_doc_id,
                    embedding=emb,
                )
            )
            inserted += 1
            if emb:
                embedded += 1

    await session.commit()
    return {"inserted": inserted, "updated": updated, "embedded": embedded}

