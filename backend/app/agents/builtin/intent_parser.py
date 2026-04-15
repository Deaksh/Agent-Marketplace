from __future__ import annotations

from app.agents.base import AgentSpec


class IntentParserAgent:
    spec = AgentSpec(
        name="intent_parser",
        description="Classifies user intent into a known compliance workflow and extracts key attributes.",
        input_schema={
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "context": {"type": "object"},
            },
            "required": ["intent"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "workflow": {"type": "string"},
                "regulation_code": {"type": "string"},
                "system_type": {"type": "string"},
                "signals": {"type": "object"},
            },
            "required": ["workflow", "regulation_code"],
        },
        cost_estimate_usd=0.0,
        reliability_score=0.9,
    )

    async def run(self, *, intent: str, context: dict, state: dict) -> dict:
        text = (intent or "").lower()
        workflow = "gdpr_compliance_check" if ("gdpr" in text or context.get("region") in {"EU", "EEA"}) else "regulation_lookup"
        regulation_code = "GDPR" if ("gdpr" in text or context.get("region") in {"EU", "EEA"}) else "UNKNOWN"

        # Very lightweight extraction; designed to be replaced with LLM function-calls.
        system_type = "unknown"
        if any(k in text for k in ["hiring", "recruit", "candidate", "cv"]):
            system_type = "hiring"
        elif any(k in text for k in ["chatbot", "assistant", "support"]):
            system_type = "chatbot"

        signals = {
            "mentions_pii": any(k in text for k in ["pii", "personal data", "name", "email"]),
            "mentions_biometric": any(k in text for k in ["biometric", "face", "voice", "fingerprint"]),
            "region": context.get("region"),
            "data_types": context.get("data_types", []),
        }
        state["workflow"] = workflow
        state["regulation_code"] = regulation_code
        state["system_type"] = system_type
        state["signals"] = signals
        return {
            "workflow": workflow,
            "regulation_code": regulation_code,
            "system_type": system_type,
            "signals": signals,
        }

