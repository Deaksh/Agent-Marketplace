from __future__ import annotations

from app.agents.base import AgentSpec
from app.retrieval.regulations import RegulationRetriever


class RegulationRetrieverAgent:
    spec = AgentSpec(
        name="regulation_retriever",
        description="Retrieves relevant regulation units (e.g., GDPR articles) from the regulation_units store.",
        input_schema={
            "type": "object",
            "properties": {
                "regulation_code": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["regulation_code", "query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "snippets": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["snippets"],
        },
        cost_estimate_usd=0.0,
        reliability_score=0.85,
    )

    def __init__(self, retriever: RegulationRetriever) -> None:
        self._retriever = retriever

    async def run(self, *, intent: str, context: dict, state: dict) -> dict:
        regulation_code = state.get("regulation_code") or context.get("regulation_code") or "GDPR"
        query = context.get("query") or intent
        snippets = await self._retriever.search(regulation_code=regulation_code, query=query, limit=8)
        out = {
            "snippets": [
                {
                    "regulation_code": s.regulation_code,
                    "unit_id": s.unit_id,
                    "title": s.title,
                    "text": s.text,
                    "version": s.version,
                    "score": s.score,
                    "metadata": s.metadata,
                }
                for s in snippets
            ]
        }
        state["regulation_snippets"] = out["snippets"]
        return out

