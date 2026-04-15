from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
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
        q = (
            select(RegulationUnit)
            .where(RegulationUnit.regulation_code == regulation_code)
            .where(RegulationUnit.text.ilike(f"%{query}%"))
            .limit(limit)
        )
        rows = (await self._session.execute(q)).scalars().all()
        # naive scoring: longer overlap-ish proxy
        snippets: list[RegulationSnippet] = []
        for r in rows:
            score = min(1.0, 0.4 + (len(query) / max(1, len(r.text))) * 4)
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
        return sorted(snippets, key=lambda s: s.score, reverse=True)

