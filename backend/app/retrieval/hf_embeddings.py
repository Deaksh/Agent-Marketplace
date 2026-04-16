from __future__ import annotations

from typing import Any

import httpx


class HfEmbeddingClient:
    """
    Hugging Face Inference API embedding client.

    Uses the "feature-extraction" pipeline via the public inference endpoint.
    """

    def __init__(self, *, token: str, model: str) -> None:
        self._token = token
        self._model = model

    async def embed(self, *, text: str, timeout_s: float = 25.0) -> list[float]:
        url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{self._model}"
        headers = {"authorization": f"Bearer {self._token}"}
        payload: dict[str, Any] = {"inputs": text}

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # HF can return:
        # - [dim] (single vector)
        # - [[dim]] or [[...], [...]] (token embeddings)
        if isinstance(data, list) and data and isinstance(data[0], (int, float)):
            return [float(x) for x in data]
        if isinstance(data, list) and data and isinstance(data[0], list):
            # mean-pool across token vectors
            vectors: list[list[float]] = [[float(x) for x in row] for row in data]  # type: ignore[arg-type]
            dim = len(vectors[0]) if vectors else 0
            if dim == 0:
                return []
            out = [0.0] * dim
            for row in vectors:
                for i, v in enumerate(row):
                    out[i] += v
            return [v / max(1, len(vectors)) for v in out]

        raise ValueError("Unexpected HF embedding response shape")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return float(dot / ((na**0.5) * (nb**0.5)))

