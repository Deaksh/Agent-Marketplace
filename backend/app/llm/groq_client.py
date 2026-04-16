from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class GroqChatResult:
    text: str
    json: dict[str, Any] | None
    raw: dict[str, Any]


class GroqClient:
    """
    Minimal Groq client using the OpenAI-compatible API.

    We intentionally avoid adding the `openai` SDK to keep the MVP lightweight.
    """

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        json_schema_hint: dict[str, Any] | None = None,
        timeout_s: float = 20.0,
    ) -> GroqChatResult:
        """
        Ask the model to return JSON. We do a best-effort parse.
        """

        schema_hint = ""
        if json_schema_hint:
            schema_hint = "\nReturn STRICT JSON matching this schema:\n" + json.dumps(json_schema_hint, indent=2)

        payload = {
            "model": self._model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system.strip()},
                {
                    "role": "user",
                    "content": (user.strip() + schema_hint + "\n\nReturn ONLY JSON.").strip(),
                },
            ],
        }

        headers = {"authorization": f"Bearer {self._api_key}", "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(f"{self._base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            raw = resp.json()

        text = (
            raw.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(text)
        except Exception:  # noqa: BLE001
            parsed = None

        return GroqChatResult(text=text, json=parsed, raw=raw)

