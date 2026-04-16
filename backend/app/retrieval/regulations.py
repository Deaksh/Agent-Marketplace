from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RegulationUnit


@dataclass(frozen=True)
class RegulationSnippet:
    regulation_code: str
    unit_id: str
    title: str
    text: str
    version: str
    score: float
    metadata: dict[str, Any]


class RegulationRetriever:
    """
    MVP semantic retrieval interface.

    For now:
    - uses a simple keyword / LIKE search over `regulation_units.text`
    - returns scored snippets

    This is designed to be swapped for:
    - embeddings + pgvector
    - hybrid retrieval (BM25 + vectors)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        *,
        regulation_code: str,
        query: str,
        limit: int = 8,
    ) -> list[RegulationSnippet]:
        # Tokenize query into a few meaningful terms to avoid a single long LIKE.
        raw = (query or "").strip()
        tokens = [t for t in (raw.replace("/", " ").replace("-", " ").split()) if len(t) >= 4]
        tokens = tokens[:6]  # cap for perf

        base = select(RegulationUnit).where(RegulationUnit.regulation_code == regulation_code)
        if tokens:
            base = base.where(or_(*[RegulationUnit.text.ilike(f"%{t}%") for t in tokens]))
        else:
            base = base.where(RegulationUnit.text.ilike(f"%{raw}%")) if raw else base

        rows = (await self._session.execute(base.limit(limit * 4))).scalars().all()

        # naive scoring: token match count + small length normalization
        snippets: list[RegulationSnippet] = []
        for r in rows:
            text_l = (r.text or "").lower()
            token_hits = sum(1 for t in tokens if t.lower() in text_l) if tokens else (1 if raw.lower() in text_l else 0)
            score = min(1.0, 0.25 + 0.15 * token_hits + (min(800, len(r.text or "")) / 8000))
            snippets.append(
                RegulationSnippet(
                    regulation_code=r.regulation_code,
                    unit_id=r.unit_id,
                    title=r.title,
                    text=r.text,
                    version=r.version,
                    score=score,
                    metadata=r.meta or {},
                )
            )

        # Fallback: if nothing matched, just return some units so downstream can still produce an answer,
        # but with lower confidence.
        if not snippets:
            rows2 = (
                (await self._session.execute(base.limit(limit)))
                .scalars()
                .all()
            )
            for r in rows2:
                snippets.append(
                    RegulationSnippet(
                        regulation_code=r.regulation_code,
                        unit_id=r.unit_id,
                        title=r.title,
                        text=r.text,
                        version=r.version,
                        score=0.05,
                        metadata=r.meta or {},
                    )
                )

        return sorted(snippets, key=lambda s: s.score, reverse=True)[:limit]

