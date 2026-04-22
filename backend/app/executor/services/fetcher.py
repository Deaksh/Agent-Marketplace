from __future__ import annotations

import logging
from typing import Any

import httpx

from app.executor.config.settings import executor_settings

logger = logging.getLogger("executor")


def _base() -> str:
    return executor_settings.watchtower_base_url.rstrip("/")


async def _get_json_first_ok(*, client: httpx.AsyncClient, urls: list[str]) -> dict[str, Any]:
    """Try GET URLs in order; use first non-404 response (raise on other HTTP errors)."""
    last_404: httpx.Response | None = None
    for url in urls:
        resp = await client.get(url)
        if resp.status_code == 404:
            last_404 = resp
            continue
        resp.raise_for_status()
        return resp.json()
    if last_404 is not None:
        last_404.raise_for_status()
    raise RuntimeError("executor: empty URL list for GET")


async def fetch_task(*, task_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
    data = await _get_json_first_ok(
        client=client,
        urls=[f"{_base()}/tasks/{task_id}"],
    )
    if isinstance(data, dict) and "id" not in data:
        tid = data.get("task_id") or task_id
        data = {**data, "id": str(tid)}
    return data


def _pick_regulation_from_collection(raw: Any, regulation_id: str) -> dict[str, Any] | None:
    """Handle GET /regulations list shapes: list, or dict with common list keys."""
    rows: list[Any] = []
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        for key in ("items", "regulations", "data", "results"):
            v = raw.get(key)
            if isinstance(v, list):
                rows = v
                break
        if not rows and "id" in raw:
            rows = [raw]
    rid = str(regulation_id).strip()
    for item in rows:
        if not isinstance(item, dict):
            continue
        for k in ("id", "regulation_id", "code", "unit_id"):
            if str(item.get(k) or "").strip() == rid:
                return item
    return None


async def fetch_regulation(*, regulation_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
    base = _base()
    try:
        return await _get_json_first_ok(
            client=client,
            urls=[f"{base}/regulations/{regulation_id}"],
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise
    # Beacon lists /regulations without /{id}; pick from collection.
    resp = await client.get(f"{base}/regulations")
    resp.raise_for_status()
    raw = resp.json()
    picked = _pick_regulation_from_collection(raw, regulation_id)
    if picked is None:
        logger.warning("regulation_not_in_collection regulation_id=%s", regulation_id)
        return {"id": regulation_id, "text": "", "units": [], "meta": {}}
    return picked


async def fetch_model(*, model_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
    base = _base()
    data = await _get_json_first_ok(
        client=client,
        urls=[
            f"{base}/models/{model_id}",
            f"{base}/company/models/{model_id}",
        ],
    )
    if isinstance(data, dict) and "id" not in data:
        mid = data.get("model_id") or model_id
        data = {**data, "id": str(mid)}
    return data


async def post_result(*, task_id: str, payload: dict[str, Any], client: httpx.AsyncClient) -> None:
    if executor_settings.skip_result_post:
        logger.info("skip_result_post task_id=%s (set EXECUTOR_SKIP_RESULT_POST=true)", task_id)
        return
    resp = await client.post(f"{_base()}/tasks/{task_id}/result", json=payload)
    resp.raise_for_status()
