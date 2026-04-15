from __future__ import annotations

from app.agents.base import AgentSpec


class ObligationMapperAgent:
    spec = AgentSpec(
        name="obligation_mapper",
        description="Maps retrieved regulation units to practical obligations and checks for likely gaps based on provided context.",
        input_schema={
            "type": "object",
            "properties": {
                "regulation_snippets": {"type": "array"},
                "context": {"type": "object"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "obligations": {"type": "array", "items": {"type": "object"}},
                "gaps": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["obligations", "gaps"],
        },
        cost_estimate_usd=0.0,
        reliability_score=0.8,
    )

    async def run(self, *, intent: str, context: dict, state: dict) -> dict:
        snippets = state.get("regulation_snippets") or []
        data_types = set((context.get("data_types") or []) + (state.get("signals", {}).get("data_types") or []))
        obligations = []
        gaps = []

        # MVP heuristics: treat certain common GDPR obligations as checklist items.
        base = [
            ("lawful_basis", "Establish a lawful basis for processing personal data."),
            ("transparency", "Provide transparent notices (privacy policy) describing data use."),
            ("data_minimization", "Collect only the minimum necessary personal data."),
            ("security", "Implement appropriate technical and organizational measures."),
            ("dpa", "If using processors/vendors, execute a Data Processing Agreement (DPA)."),
        ]
        if "biometric" in {d.lower() for d in data_types}:
            base.append(("special_category", "Special category processing requires additional conditions and safeguards."))

        for key, desc in base:
            evidence = [s for s in snippets if any(t in (s.get("unit_id", "") + " " + s.get("title", "") + " " + s.get("text", "")).lower() for t in key.split("_"))]
            obligations.append(
                {
                    "key": key,
                    "description": desc,
                    "evidence_units": [e.get("unit_id") for e in evidence[:3]],
                }
            )

        # Gaps from context omissions (MVP)
        if not context.get("company"):
            gaps.append({"key": "missing_company_context", "severity": "medium", "description": "Company/context details missing; assessment may be incomplete."})
        if "PII" in data_types and not context.get("data_retention"):
            gaps.append({"key": "data_retention_unspecified", "severity": "high", "description": "Data retention policy not specified for personal data."})
        if not context.get("dpia_done") and state.get("system_type") in {"hiring"}:
            gaps.append({"key": "dpia_likely_required", "severity": "high", "description": "A DPIA is often required for high-risk processing (e.g., hiring decisions)."})

        state["obligations"] = obligations
        state["gaps"] = gaps
        return {"obligations": obligations, "gaps": gaps}

