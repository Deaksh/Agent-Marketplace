from __future__ import annotations

from app.agents.base import AgentSpec


class ReportGeneratorAgent:
    spec = AgentSpec(
        name="report_generator",
        description="Generates a human-readable compliance report and structured recommendations from aggregated signals.",
        input_schema={
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "risk_score": {"type": "number"},
                "obligations": {"type": "array"},
                "gaps": {"type": "array"},
                "risks": {"type": "array"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "recommendations": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["result", "recommendations"],
        },
        cost_estimate_usd=0.0,
        reliability_score=0.78,
    )

    async def run(self, *, intent: str, context: dict, state: dict) -> dict:
        risk_score = float(state.get("risk_score") or 0.0)
        obligations = state.get("obligations") or []
        gaps = state.get("gaps") or []
        risks = state.get("risks") or []
        reg = state.get("regulation_code") or "UNKNOWN"
        persona = (context.get("persona") or "founder_pm").strip()

        # Headline should incorporate evidence/confidence, not only a risk threshold.
        explainability = state.get("explainability") or {}
        checks = {c.get("check"): c for c in (explainability.get("checks") or []) if isinstance(c, dict)}
        evidence_ok = bool((checks.get("evidence_sufficient") or {}).get("ok"))
        confidence = float(state.get("confidence") or 0.0)

        if not evidence_ok:
            headline = "Not enough evidence; provide missing inputs / artifacts"
        elif confidence >= 0.85 and risk_score < 0.55:
            headline = "Likely compliant with actionable gaps to address"
        else:
            headline = "Compliance risk elevated; remediation recommended"

        lines = [
            f"Outcome Execution Layer Report ({reg})",
            "",
            f"Intent: {intent}",
            f"Persona: {persona}",
            f"Assessment headline: {headline}",
            f"Risk score: {risk_score:.2f} (0=low, 1=high)",
            "",
            "Key obligations considered:",
        ]
        for o in obligations[:8]:
            ev = ", ".join(o.get("evidence_units") or [])
            lines.append(f"- {o.get('description')}" + (f" (evidence: {ev})" if ev else ""))

        if gaps:
            lines.append("")
            lines.append("Detected gaps / missing evidence:")
            for g in gaps[:10]:
                lines.append(f"- [{(g.get('severity') or 'unknown').upper()}] {g.get('description')}")

        if risks:
            lines.append("")
            lines.append("Key risks:")
            for r in risks[:10]:
                lines.append(f"- [{(r.get('severity') or 'unknown').upper()}] {r.get('description')}")

        recommendations = []

        # Persona-tailored next actions (always included as the first item).
        if persona == "founder_pm":
            recommendations.append(
                {
                    "title": "Define ship criteria and assign owners",
                    "why": "Shipping requires clear gates tied to evidence and controls.",
                    "how": "Convert top gaps into acceptance criteria; assign owners/dates; link evidence artifacts (DPIA, retention policy, notices).",
                }
            )
        elif persona == "security":
            recommendations.append(
                {
                    "title": "Create a controls evidence pack",
                    "why": "Security reviews require demonstrable controls and traceability.",
                    "how": "Document access control, encryption, logging/monitoring, and incident response; map each control to obligations.",
                }
            )
        elif persona == "legal_ops":
            recommendations.append(
                {
                    "title": "Prepare legal artifacts for defensibility",
                    "why": "Legal conclusions must be supported by lawful basis and documentation.",
                    "how": "Confirm lawful basis; update notices; ensure DPAs/subprocessor list; maintain RoPA and DPIA where required.",
                }
            )
        elif persona == "sales_eng":
            recommendations.append(
                {
                    "title": "Generate customer questionnaire-ready answers",
                    "why": "Sales cycles need consistent, evidence-backed responses.",
                    "how": "Summarize hosting, subprocessors, certifications, retention, DPIA status, and key obligations into reusable answers.",
                }
            )

        if any(g.get("key") == "data_retention_unspecified" for g in gaps):
            recommendations.append(
                {
                    "title": "Define and enforce a data retention policy",
                    "why": "Retention is a core GDPR principle; undefined retention increases risk.",
                    "how": "Document retention periods per data type; implement deletion/archiving controls; log compliance evidence.",
                }
            )
        if any(g.get("key") == "dpia_likely_required" for g in gaps):
            recommendations.append(
                {
                    "title": "Perform a DPIA and document risk controls",
                    "why": "High-risk processing often requires DPIA prior to deployment.",
                    "how": "Run DPIA; document mitigations; track residual risks; set review cadence.",
                }
            )
        if not recommendations:
            recommendations.append(
                {
                    "title": "Create an evidence pack for auditability",
                    "why": "Compliance requires demonstrable evidence, not just intent.",
                    "how": "Maintain records of processing, policies, DPAs, and security controls; link them to each obligation.",
                }
            )

        result = "\n".join(lines)
        state["result_text"] = result
        state["recommendations"] = recommendations
        return {"result": result, "recommendations": recommendations}

