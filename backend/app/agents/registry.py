from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.agents.base import Agent, AgentSpec


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.spec.name] = agent

    def list_specs(self) -> list[AgentSpec]:
        return [a.spec for a in self._agents.values()]

    def get(self, name: str) -> Agent:
        return self._agents[name]

    def has(self, name: str) -> bool:
        return name in self._agents

    def names(self) -> list[str]:
        return sorted(self._agents.keys())

    def __iter__(self) -> Iterable[tuple[str, Agent]]:
        return iter(self._agents.items())


def spec_to_dict(spec: AgentSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.input_schema,
        "output_schema": spec.output_schema,
        "cost_estimate_usd": spec.cost_estimate_usd,
        "reliability_score": spec.reliability_score,
    }

