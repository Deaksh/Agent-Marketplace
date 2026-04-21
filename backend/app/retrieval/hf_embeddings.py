from __future__ import annotations

import asyncio
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

    async def embed(
        self,
        *,
        text: str,
        timeout_s: float = 60.0,
        max_attempts: int = 4,
    ) -> list[float]:
        # HF changed public Inference API routing for pipeline tasks for many models.
        # For feature-extraction embeddings, the router endpoint is the most reliable:
        #   https://router.huggingface.co/hf-inference/models/<model>/pipeline/feature-extraction
        #
        # We keep a fallback to the legacy api-inference /models endpoint for older models,
        # but note that its input schema varies by task.
        urls = [
            f"https://router.huggingface.co/hf-inference/models/{self._model}/pipeline/feature-extraction",
            f"https://api-inference.huggingface.co/models/{self._model}",
        ]
        headers = {"authorization": f"Bearer {self._token}"}
        payload: dict[str, Any] = {
            "inputs": text,
            "options": {"wait_for_model": True},
        }

        last_exc: Exception | None = None
        data: Any | None = None
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            # Try each endpoint; for transient failures, retry with backoff.
            for url in urls:
                for attempt in range(max_attempts):
                    try:
                        resp = await client.post(url, headers=headers, json=payload)
                        # If the model is still warming up, HF commonly returns 503 with an
                        # `estimated_time` field; we retry with backoff.
                        if resp.status_code in {429, 503, 504}:
                            try:
                                body = resp.json()
                            except Exception:  # noqa: BLE001
                                body = None
                            est = None
                            if isinstance(body, dict):
                                est = body.get("estimated_time")
                            # Backoff: use HF hint when present, otherwise exponential.
                            delay_s = float(est) if isinstance(est, (int, float)) else float(min(8.0, 0.75 * (2**attempt)))
                            await asyncio.sleep(max(0.25, min(12.0, delay_s)))
                            continue

                        # If an endpoint doesn't exist for this model/task, try next url.
                        if resp.status_code == 404:
                            break

                        if resp.status_code >= 400:
                            # Bubble up a useful message; HF often returns JSON with details.
                            body_text = resp.text
                            raise httpx.HTTPStatusError(
                                f"HTTP {resp.status_code} from HF ({url}): {body_text[:500]}",
                                request=resp.request,
                                response=resp,
                            )

                        data = resp.json()
                        break
                    except Exception as e:  # noqa: BLE001
                        last_exc = e
                        # Retry a couple of transient network failures as well.
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(float(min(8.0, 0.75 * (2**attempt))))
                            continue
                        # Try next URL after final attempt for this URL.
                        break
                else:
                    # no break => exhausted attempts for this URL; try next URL
                    continue

                # We only reach here if we got a response body (`data`) or a 404 break.
                if data is not None:
                    break
            else:
                if last_exc:
                    raise last_exc
                raise RuntimeError("HF embedding request failed without exception")

        if data is None:
            # We tried all known endpoints; surface the last exception.
            raise RuntimeError("HF embedding request failed (no response body)") from last_exc

        if isinstance(data, dict) and "error" in data:
            # HF sometimes returns 200 with an error payload.
            raise RuntimeError(str(data.get("error") or "HF inference error"))

        # HF can return:
        # - [dim] (single vector)
        # - [[...], [...]] (token embeddings)
        # - [[[...], [...]]] (batch dimension + token embeddings)
        if isinstance(data, list) and data and isinstance(data[0], (int, float)):
            return [float(x) for x in data]

        # Unwrap a single-item batch if present: [[[...], [...]]] -> [[...], [...]]
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], list) and data[0] and isinstance(data[0][0], list):
            data = data[0]

        if isinstance(data, list) and data and isinstance(data[0], list):
            # mean-pool across token vectors: [tokens][dim]
            vectors: list[list[float]] = []
            for row in data:
                if not isinstance(row, list):
                    continue
                if row and isinstance(row[0], list):
                    raise ValueError("Unexpected HF embedding response shape (extra nesting)")
                vectors.append([float(x) for x in row])

            dim = len(vectors[0]) if vectors else 0
            if dim == 0:
                return []
            out = [0.0] * dim
            for row in vectors:
                # Guard against ragged tokens
                if len(row) != dim:
                    continue
                for i, v in enumerate(row):
                    out[i] += v
            denom = max(1, len(vectors))
            return [v / denom for v in out]

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

