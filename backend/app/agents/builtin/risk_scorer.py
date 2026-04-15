from __future__ import annotations

from app.agents.base import AgentSpec


class RiskScorerAgent:
    spec = AgentSpec(
        name="risk_scorer",
        description="Computes a risk score and key risks from identified gaps and context signals.",
        input_schema={
            "type": "object",
            "properties": {
                "gaps": {"type": "array"},
                "signals": {"type": "object"},
                "context": {"type": "object"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "risk_score": {"type": "number"},
                "risks": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["risk_score", "risks"],
        },
        cost_estimate_usd=0.0,
        reliability_score=0.82,
    )

    async def run(self, *, intent: str, context: dict, state: dict) -> dict:
        gaps = state.get("gaps") or []
        signals = state.get("signals") or {}
        system_type = state.get("system_type") or "unknown"

        score = 0.25
        risks = []
        for g in gaps:
            sev = (g.get("severity") or "low").lower()
            inc = {"low": 0.05, "medium": 0.12, "high": 0.22}.get(sev, 0.08)
            score += inc
            risks.append(
                {
                    "key": g.get("key"),
                    "severity": sev,
                    "description": g.get("description"),
                    "mitigation_hint": "Address the gap and document controls; retain evidence for audit.",
                }
            )

        if signals.get("mentions_biometric"):
            score += 0.18
            risks.append(
                {
                    "key": "biometric_processing",
                    "severity": "high",
                    "description": "Biometric data is generally special category; requires stronger legal basis and safeguards.",
                    "mitigation_hint": "Confirm Art. 9 conditions, consent/necessity, minimize collection, and document DPIA.",
                }
            )
        if system_type == "hiring":
            score += 0.12
            risks.append(
                {
                    "key": "automated_decision_making",
                    "severity": "medium",
                    "description": "Hiring tools may involve automated decision-making or profiling with additional obligations.",
                    "mitigation_hint": "Ensure human review, transparency, contestability, and record-keeping.",
                }
            )

        score = max(0.0, min(1.0, score))
        state["risk_score"] = score
        state["risks"] = risks
        return {"risk_score": score, "risks": risks}

