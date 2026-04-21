from __future__ import annotations

from typing import Any

import httpx

from app.executor.config.settings import executor_settings


def _base() -> str:
    return executor_settings.watchtower_base_url.rstrip("/")


async def fetch_task(*, task_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get(f"{_base()}/tasks/{task_id}")
    resp.raise_for_status()
    return resp.json()


async def fetch_regulation(*, regulation_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get(f"{_base()}/regulations/{regulation_id}")
    resp.raise_for_status()
    return resp.json()


async def fetch_model(*, model_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get(f"{_base()}/models/{model_id}")
    resp.raise_for_status()
    return resp.json()


async def post_result(*, task_id: str, payload: dict[str, Any], client: httpx.AsyncClient) -> None:
    resp = await client.post(f"{_base()}/tasks/{task_id}/result", json=payload)
    resp.raise_for_status()

