from __future__ import annotations

from typing import Any

import httpx

from app.agents.base import AgentSpec
from app.core.config import settings


class RemoteHttpMarketplaceAgent:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        endpoint_url: str,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        cost_estimate_usd: float,
        reliability_score: float,
        timeout_s: float = 20.0,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._timeout_s = timeout_s
        self.spec = AgentSpec(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            cost_estimate_usd=cost_estimate_usd,
            reliability_score=reliability_score,
        )

    async def run(self, *, intent: str, context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        if settings.marketplace_remote_allowlist:
            allowed = any(self._endpoint_url.startswith(prefix) for prefix in settings.marketplace_remote_allowlist)
            if not allowed:
                raise ValueError("Remote agent endpoint not in allowlist")

        payload = {"intent": intent, "context": context, "state": state}
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.post(self._endpoint_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict):
            return {"result": data}
        return data

