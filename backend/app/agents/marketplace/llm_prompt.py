from __future__ import annotations

from typing import Any

from app.agents.base import AgentSpec
from app.core.config import settings
from app.llm.groq_client import GroqClient


class LlmPromptMarketplaceAgent:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        prompt_template: str,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        cost_estimate_usd: float,
        reliability_score: float,
    ) -> None:
        self._prompt_template = prompt_template
        self.spec = AgentSpec(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            cost_estimate_usd=cost_estimate_usd,
            reliability_score=reliability_score,
        )

    async def run(self, *, intent: str, context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY not configured for llm_prompt marketplace agents")

        client = GroqClient(api_key=settings.groq_api_key, base_url=settings.groq_base_url, model=settings.groq_model)

        rendered = (
            self._prompt_template.replace("{{intent}}", intent)
            .replace("{{context}}", str(context))
            .replace("{{state}}", str(state))
        )
        res = await client.chat_json(
            system="You are a specialized compliance agent. Return only JSON.",
            user=rendered,
            json_schema_hint=self.spec.output_schema or None,
        )
        if res.json is not None and isinstance(res.json, dict):
            return res.json
        # Fallback: wrap raw response
        return {"raw_text": res.text}

