from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    cost_estimate_usd: float
    reliability_score: float  # 0..1


class Agent(Protocol):
    spec: AgentSpec

    async def run(self, *, intent: str, context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """
        Execute agent logic.

        Args:
          intent: raw user intent
          context: user-provided structured context
          state: shared mutable orchestration state (previous step outputs, retrieved docs, etc.)

        Returns:
          Structured output per spec.output_schema
        """

