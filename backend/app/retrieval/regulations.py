from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import RegulationUnit
from app.retrieval.hf_embeddings import HfEmbeddingClient, cosine_similarity


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

        # 1) Keyword shortlist
        shortlist = (await self._session.execute(base.limit(limit * 10))).scalars().all()

        # 2) Score: hybrid keyword + optional embedding rerank
        snippets: list[RegulationSnippet] = []
        query_emb: list[float] | None = None
        embedder: HfEmbeddingClient | None = None
        if settings.hf_token:
            embedder = HfEmbeddingClient(token=settings.hf_token, model=settings.hf_embedding_model)
            try:
                query_emb = await embedder.embed(text=raw or query)
            except Exception:  # noqa: BLE001
                query_emb = None

        for r in shortlist:
            text_l = (r.text or "").lower()
            token_hits = sum(1 for t in tokens if t.lower() in text_l) if tokens else (1 if raw.lower() in text_l else 0)
            kw_score = min(1.0, 0.25 + 0.15 * token_hits + (min(800, len(r.text or "")) / 8000))

            emb_score = 0.0
            if embedder and query_emb:
                try:
                    # Keep request payload small: embed (title + first chunk of text).
                    candidate_text = (r.title + "\n" + (r.text or "")[:1200]).strip()
                    cand_emb = await embedder.embed(text=candidate_text)
                    emb_score = max(0.0, cosine_similarity(query_emb, cand_emb))
                except Exception:  # noqa: BLE001
                    emb_score = 0.0

            # Weighted blend (keyword shortlist ensures we don't embed the entire corpus).
            score = float(min(1.0, (0.65 * kw_score) + (0.35 * emb_score)))
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

