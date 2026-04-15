from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    confidence: float
    checks: list[dict[str, Any]]
    notes: list[str]


class OutcomeValidator:
    """
    MVP validator layer.

    Produces:
    - confidence score (0..1)
    - explainability checks (rule-based)

    Designed to later incorporate:
    - secondary validator agents
    - cross-run consistency checks
    """

    def validate(self, *, state: dict[str, Any]) -> ValidationResult:
        checks: list[dict[str, Any]] = []
        notes: list[str] = []

        # Required artifacts
        required = [
            ("workflow", state.get("workflow")),
            ("regulation_code", state.get("regulation_code")),
            ("regulation_snippets", state.get("regulation_snippets")),
            ("obligations", state.get("obligations")),
            ("risks", state.get("risks")),
            ("result_text", state.get("result_text")),
        ]
        missing = [k for k, v in required if not v]
        checks.append({"check": "required_artifacts_present", "ok": len(missing) == 0, "missing": missing})

        # Evidence quality: at least 2 snippets for compliance checks
        snippets = state.get("regulation_snippets") or []
        evidence_ok = len(snippets) >= 2 if state.get("workflow") == "gdpr_compliance_check" else True
        checks.append({"check": "evidence_sufficient", "ok": evidence_ok, "snippet_count": len(snippets)})

        risk_score = float(state.get("risk_score") or 0.0)
        checks.append({"check": "risk_score_in_range", "ok": 0.0 <= risk_score <= 1.0, "risk_score": risk_score})

        # Confidence heuristic
        confidence = 0.55
        if len(missing) == 0:
            confidence += 0.15
        if evidence_ok:
            confidence += 0.15
        if len(snippets) >= 5:
            confidence += 0.05

        # Penalize if UNKNOWN regulation
        if (state.get("regulation_code") or "") == "UNKNOWN":
            confidence -= 0.25
            notes.append("Regulation could not be confidently inferred; results may be incomplete.")

        confidence = max(0.0, min(1.0, confidence))
        return ValidationResult(confidence=confidence, checks=checks, notes=notes)

