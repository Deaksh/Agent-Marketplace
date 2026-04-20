from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from app.core.config import settings
from app.retrieval.hf_embeddings import HfEmbeddingClient


@dataclass(frozen=True)
class EmbedResult:
    vector: list[float]
    provider: str


def _hash_embed(*, text: str, dim: int) -> list[float]:
    """
    Deterministic, zero-dependency embedding fallback.

    This is NOT semantically strong, but it keeps the system functional in dev
    without HF/OpenAI tokens and lets pgvector plumbing work end-to-end.
    """
    dim = max(8, int(dim))
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand bytes deterministically.
    buf = bytearray(h)
    while len(buf) < dim * 4:
        buf.extend(hashlib.sha256(buf).digest())
    floats: list[float] = []
    for i in range(dim):
        chunk = buf[i * 4 : i * 4 + 4]
        n = int.from_bytes(chunk, "little", signed=False)
        # Map to [-1, 1]
        x = (n / 2**32) * 2.0 - 1.0
        floats.append(float(x))
    # L2 normalize
    norm = math.sqrt(sum(x * x for x in floats)) or 1.0
    return [x / norm for x in floats]


class Embedder:
    async def embed(self, *, text: str) -> EmbedResult:  # pragma: no cover
        raise NotImplementedError


class ConfigurableEmbedder(Embedder):
    def __init__(self) -> None:
        self._dim = int(settings.rag_embedding_dim or 384)
        self._hf: HfEmbeddingClient | None = None
        if settings.hf_token:
            self._hf = HfEmbeddingClient(token=settings.hf_token, model=settings.hf_embedding_model)

    async def embed(self, *, text: str) -> EmbedResult:
        t = (text or "").strip()
        if self._hf:
            vec = await self._hf.embed(text=t)
            # HF models may return different dim than configured; keep as-is.
            return EmbedResult(vector=[float(x) for x in vec], provider="hf_inference")
        return EmbedResult(vector=_hash_embed(text=t, dim=self._dim), provider="hash_fallback")

