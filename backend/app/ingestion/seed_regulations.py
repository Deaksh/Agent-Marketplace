from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RegulationUnit
from app.retrieval.embedder import ConfigurableEmbedder


SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "gdpr_seed_units.json"


async def seed_regulation_units(*, session: AsyncSession) -> dict[str, Any]:
    """
    Idempotent seed of a minimal regulation corpus for MVP demos/dev.

    If your real ingestion pipelines populate `regulation_units`, you should NOT use this.
    """
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    inserted = 0
    updated = 0
    embedded = 0

    embedder = ConfigurableEmbedder()

    for u in raw:
        code = u["regulation_code"]
        unit_id = u["unit_id"]
        meta = u.get("meta", {}) or {}

        # Minimal metadata normalization for enterprise retrieval.
        source_url = meta.get("source_url") or meta.get("source")
        jurisdiction = meta.get("jurisdiction") or ("EU" if str(code).upper() == "GDPR" else None)

        text_for_embedding = (u.get("title", "") + "\n" + (u.get("text", "") or "")).strip()
        emb: list[float] | None = None
        if text_for_embedding:
            try:
                emb = (await embedder.embed(text=text_for_embedding)).vector
            except Exception:  # noqa: BLE001
                emb = None
        existing = (
            (await session.execute(select(RegulationUnit).where(RegulationUnit.regulation_code == code).where(RegulationUnit.unit_id == unit_id)))
            .scalars()
            .first()
        )
        if existing:
            existing.title = u.get("title", existing.title)
            existing.text = u.get("text", existing.text)
            existing.version = u.get("version", existing.version)
            existing.meta = meta
            existing.source_url = source_url
            existing.jurisdiction = jurisdiction
            if emb:
                existing.embedding = emb
                embedded += 1
            await session.merge(existing)
            updated += 1
        else:
            session.add(
                RegulationUnit(
                    regulation_code=code,
                    unit_id=unit_id,
                    title=u.get("title", ""),
                    text=u.get("text", ""),
                    version=u.get("version", "seed"),
                    meta=meta,
                    source_url=source_url,
                    jurisdiction=jurisdiction,
                    embedding=emb,
                )
            )
            inserted += 1
            if emb:
                embedded += 1

    await session.commit()
    return {"inserted": inserted, "updated": updated, "embedded": embedded, "source": str(SEED_PATH)}

