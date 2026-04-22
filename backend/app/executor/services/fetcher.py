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
    base = _base()
    url = f"{base}/tasks/{task_id}"
    method = executor_settings.watchtower_task_http_method.strip().upper()
    if method == "GET":
        resp = await client.get(url)
    elif method == "POST":
        resp = await client.post(url, json={})
    elif method == "PATCH":
        # Beacon declares PATCH /tasks/{id}. We treat it as "fetch" by sending an empty object.
        resp = await client.patch(url, json={})
    else:
        raise ValueError(f"Unsupported watchtower_task_http_method: {method!r}")

    # Some Beacon deployments may only allow admin GET under /admin/tasks/{id}.
    if resp.status_code == 405:
        admin_url = f"{base}/admin/tasks/{task_id}"
        if method == "PATCH":
            admin_resp = await client.patch(admin_url, json={})
        else:
            admin_resp = await client.get(admin_url)
        admin_resp.raise_for_status()
        data = admin_resp.json()
    else:
        resp.raise_for_status()
        data = resp.json()

    # Beacon PATCH /tasks/{id} often returns {"status": "no_changes"} rather than a task object.
    # In that case, fall back to GET /tasks and select the matching row.
    if isinstance(data, dict) and data.get("status") == "no_changes":
        list_resp = await client.get(f"{base}/tasks")
        list_resp.raise_for_status()
        rows = list_resp.json()
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict) and str(r.get("id")) == str(task_id):
                    data = r
                    break

    # Beacon /api/execution/tasks/{id} may return {"task": {...}, "regulation": {...}, "model": {...}}
    if isinstance(data, dict) and isinstance(data.get("task"), dict):
        task_obj = data.get("task") or {}
        # keep related objects accessible to downstream derivation logic
        task_obj = {
            **task_obj,
            "regulation": data.get("regulation"),
            "model": data.get("model"),
        }
        data = task_obj

    if isinstance(data, dict) and "id" not in data:
        tid = data.get("task_id") or task_id
        data = {**data, "id": str(tid)}
    return data


async def fetch_task_events(*, task_id: str, client: httpx.AsyncClient) -> Any:
    resp = await client.get(f"{_base()}/tasks/{task_id}/events")
    resp.raise_for_status()
    return resp.json()


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


async def fetch_regulation(*, regulation_id: str | int, client: httpx.AsyncClient) -> dict[str, Any]:
    base = _base()
    regulation_id = str(regulation_id)
    try:
        data = await _get_json_first_ok(
            client=client,
            urls=[f"{base}/regulations/{regulation_id}"],
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise
        data = {}

    # Beacon /api/execution/regulations/{id} may return {"regulation": {...}}.
    if isinstance(data, dict) and isinstance(data.get("regulation"), dict):
        data = data["regulation"]

    if isinstance(data, dict) and "id" not in data:
        data = {**data, "id": regulation_id}
    if data:
        return data

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
    try:
        data = await _get_json_first_ok(
            client=client,
            urls=[
                f"{base}/models/{model_id}",
                f"{base}/company/models/{model_id}",
            ],
        )
    except httpx.HTTPStatusError as e:
        # Beacon may expose /company/models/{id} but not allow GET (405). Fall back to collection.
        if e.response.status_code not in (404, 405):
            raise
        data = {}

    # Beacon may wrap as {"model": {...}}
    if isinstance(data, dict) and isinstance(data.get("model"), dict):
        data = data["model"]

    if not data:
        # Try model collections. Some Beacon deployments use /models only (no /company/models).
        for collection_path in ("/company/models", "/models"):
            resp = await client.get(f"{base}{collection_path}")
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            raw = resp.json()
            if isinstance(raw, dict) and isinstance(raw.get("models"), list):
                raw = raw["models"]
            rows: list[Any] = raw if isinstance(raw, list) else []
            for r in rows:
                if isinstance(r, dict) and str(r.get("id")) == str(model_id):
                    data = r
                    break
            if data:
                break

    if not data:
        logger.warning("model_not_found model_id=%s", model_id)
        data = {"id": model_id, "description": "", "meta": {}}

    if isinstance(data, dict) and "id" not in data:
        mid = data.get("model_id") or model_id
        data = {**data, "id": str(mid)}
    return data


async def post_result(*, task_id: str, payload: dict[str, Any], client: httpx.AsyncClient) -> None:
    if executor_settings.skip_result_post:
        logger.info("skip_result_post task_id=%s (set EXECUTOR_SKIP_RESULT_POST=true)", task_id)
        return
    # Beacon doesn't implement POST /tasks/{id}/result; write back via PATCH /tasks/{id}.
    resp = await client.patch(
        f"{_base()}/tasks/{task_id}",
        json={
            "executor_result": payload,
            "executor_status": "completed",
        },
    )
    resp.raise_for_status()
