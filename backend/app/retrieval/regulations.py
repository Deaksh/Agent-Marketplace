from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import RegulationUnit
from app.retrieval.embedder import ConfigurableEmbedder
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
        jurisdiction: str | None = None,
        effective_at: datetime | None = None,
        limit: int = 8,
    ) -> list[RegulationSnippet]:
        # Postgres+pgvector path (enterprise retrieval).
        if settings.database_url.startswith("postgres"):
            return await self._search_pgvector(
                regulation_code=regulation_code,
                query=query,
                jurisdiction=jurisdiction,
                effective_at=effective_at,
                limit=limit,
            )

        # Tokenize query into a few meaningful terms to avoid a single long LIKE.
        raw = (query or "").strip()
        tokens = [t for t in (raw.replace("/", " ").replace("-", " ").split()) if len(t) >= 4]
        tokens = tokens[:6]  # cap for perf

        base_all = select(RegulationUnit).where(RegulationUnit.regulation_code == regulation_code)

        # 1) Keyword shortlist (best-effort). If it yields nothing, fall back to a regulation-code-only shortlist.
        if tokens:
            base_keyword = base_all.where(or_(*[RegulationUnit.text.ilike(f"%{t}%") for t in tokens]))
        else:
            base_keyword = base_all.where(RegulationUnit.text.ilike(f"%{raw}%")) if raw else base_all

        candidates = (await self._session.execute(base_keyword.limit(limit * 10))).scalars().all()
        if not candidates:
            candidates = (await self._session.execute(base_all.limit(limit * 10))).scalars().all()

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

        # Avoid embedding the entire corpus: rerank the top N candidates.
        embed_limit = 20
        cand_emb_cache: dict[str, list[float]] = {}

        for i, r in enumerate(candidates):
            text_l = (r.text or "").lower()
            token_hits = sum(1 for t in tokens if t.lower() in text_l) if tokens else (1 if raw.lower() in text_l else 0)
            kw_score = min(1.0, 0.25 + 0.15 * token_hits + (min(800, len(r.text or "")) / 8000))

            emb_score = 0.0
            if embedder and query_emb and i < embed_limit:
                try:
                    # Keep request payload small: embed (title + first chunk of text).
                    candidate_text = (r.title + "\n" + (r.text or "")[:1200]).strip()
                    if r.unit_id in cand_emb_cache:
                        cand_emb = cand_emb_cache[r.unit_id]
                    else:
                        cand_emb = await embedder.embed(text=candidate_text)
                        cand_emb_cache[r.unit_id] = cand_emb
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

        return sorted(snippets, key=lambda s: s.score, reverse=True)[:limit]

    async def _search_pgvector(
        self,
        *,
        regulation_code: str,
        query: str,
        jurisdiction: str | None,
        effective_at: datetime | None,
        limit: int,
    ) -> list[RegulationSnippet]:
        raw = (query or "").strip()
        tokens = [t for t in (raw.replace("/", " ").replace("-", " ").split()) if len(t) >= 4]
        tokens = tokens[:6]
        embedder = ConfigurableEmbedder()
        emb = (await embedder.embed(text=raw or query)).vector

        # Hybrid scoring (simple + index-friendly):
        # - vector similarity (primary)
        # - keyword hit count (secondary)
        from sqlalchemy import case, literal

        kw_hits = literal(0.0)
        for t in tokens:
            kw_hits = kw_hits + case((RegulationUnit.text.ilike(f"%{t}%"), 1.0), else_=0.0)

        vec_sim = (1.0 - RegulationUnit.embedding.cosine_distance(emb))  # type: ignore[union-attr]
        kw_score = case((kw_hits >= 4.0, 1.0), else_=(0.2 + (0.2 * kw_hits)))
        score_expr = (0.8 * vec_sim) + (0.2 * kw_score)

        q = select(
            RegulationUnit,
            score_expr.label("score"),
        ).where(RegulationUnit.regulation_code == regulation_code)
        q = q.where(RegulationUnit.embedding.is_not(None))  # avoid null-vector rows

        if jurisdiction:
            q = q.where(RegulationUnit.jurisdiction == jurisdiction)

        if effective_at:
            q = q.where(or_(RegulationUnit.effective_from.is_(None), RegulationUnit.effective_from <= effective_at))
            q = q.where(or_(RegulationUnit.effective_to.is_(None), RegulationUnit.effective_to >= effective_at))

        # Sort by hybrid score.
        q = q.order_by(score_expr.desc())
        q = q.limit(max(1, min(int(limit), 50)))

        rows = (await self._session.execute(q)).all()
        snippets: list[RegulationSnippet] = []
        for r, score in rows:
            meta = dict(r.meta or {})
            # Surface normalized fields into metadata for downstream consumption.
            if r.jurisdiction:
                meta.setdefault("jurisdiction", r.jurisdiction)
            if r.source_url:
                meta.setdefault("source_url", r.source_url)
            if r.source_doc_id:
                meta.setdefault("source_doc_id", r.source_doc_id)
            if r.effective_from:
                meta.setdefault("effective_from", r.effective_from.isoformat())
            if r.effective_to:
                meta.setdefault("effective_to", r.effective_to.isoformat())

            snippets.append(
                RegulationSnippet(
                    regulation_code=r.regulation_code,
                    unit_id=r.unit_id,
                    title=r.title,
                    text=r.text,
                    version=r.version,
                    score=float(score or 0.0),
                    metadata=meta,
                )
            )
        return snippets

