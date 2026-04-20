from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import RegulationUnit
from app.retrieval.embedder import ConfigurableEmbedder


async def reembed_all_regulation_units(
    *,
    session: AsyncSession,
    framework_code: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Recompute embeddings for all regulation units (or a subset).

    Uses ConfigurableEmbedder: HF Inference when `HF_TOKEN` is set, else hash fallback.
    """
    embedder = ConfigurableEmbedder()
    stmt = select(RegulationUnit).order_by(RegulationUnit.id)
    if framework_code and str(framework_code).strip():
        fc = str(framework_code).strip().upper()
        stmt = stmt.where(RegulationUnit.framework_code == fc)
    if limit is not None and limit > 0:
        stmt = stmt.limit(int(limit))

    rows = (await session.execute(stmt)).scalars().all()

    updated = 0
    skipped_empty = 0
    errors: list[dict[str, Any]] = []

    for row in rows:
        text_for_embedding = (row.title or "").strip() + "\n" + (row.text or "").strip()
        text_for_embedding = text_for_embedding.strip()
        if not text_for_embedding:
            skipped_empty += 1
            continue
        try:
            result = await embedder.embed(text=text_for_embedding)
            row.embedding = [float(x) for x in result.vector]
            session.add(row)
            updated += 1
        except Exception as e:  # noqa: BLE001
            errors.append({"id": row.id, "unit_id": row.unit_id, "error": str(e)})

    await session.commit()

    using_hf = bool(settings.hf_token)
    out: dict[str, Any] = {
        "scanned": len(rows),
        "updated": updated,
        "skipped_empty": skipped_empty,
        "embed_provider": "hf_inference" if using_hf else "hash_fallback",
        "model": settings.hf_embedding_model if using_hf else None,
        "errors": errors,
    }
    if not using_hf:
        out["warning"] = (
            "HF_TOKEN is not set; embeddings used hash fallback. "
            "Copy `.env.example` to `.env` at the repo root (or `backend/.env`) and set HF_TOKEN, "
            "then restart the API and call this endpoint again."
        )
    return out
