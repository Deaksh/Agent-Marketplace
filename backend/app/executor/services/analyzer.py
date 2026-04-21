from __future__ import annotations

from app.executor.models.schemas import AnalysisInput, AnalysisResult


async def run_compliance_analysis(*, input_data: AnalysisInput) -> AnalysisResult:
    """
    Simplified placeholder analysis.

    This should remain lightweight until Watchtower provides the canonical agent workflow.
    """
    text = (input_data.model_description + "\n" + input_data.task_context).lower()
    reg = (input_data.regulation_text or "").strip()

    if len(text.strip()) < 20:
        return AnalysisResult(
            decision="PARTIAL",
            summary="Insufficient model/system context provided to make a definitive compliance decision.",
            confidence=0.35,
            evidence={"reason": "missing_context"},
        )

    if len(reg) < 50:
        return AnalysisResult(
            decision="PARTIAL",
            summary="Regulation text was not available from Watchtower; cannot ground the assessment in evidence.",
            confidence=0.30,
            evidence={"reason": "missing_regulation_text"},
        )

    flags: list[str] = []
    if "biometric" in text:
        flags.append("biometric_data")
    if "hiring" in text or "recruit" in text:
        flags.append("employment_context")
    if "children" in text:
        flags.append("children")

    if flags:
        return AnalysisResult(
            decision="PARTIAL",
            summary="Potential high-risk indicators detected; review required before declaring full compliance.",
            confidence=0.55,
            evidence={"flags": flags},
        )

    return AnalysisResult(
        decision="COMPLIANT",
        summary="No obvious high-risk indicators detected in the provided context; preliminary compliance looks acceptable.",
        confidence=0.70,
        evidence={"flags": []},
    )

