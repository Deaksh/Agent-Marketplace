from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


DecisionValue = Literal["COMPLIANT", "NON_COMPLIANT", "NEEDS_REVIEW"]
SeverityValue = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class Citation(BaseModel):
    """
    Normalized citation for regulatory evidence.

    This is intentionally stable and explicit so exports/audits can rely on it.
    """

    regulation_code: str = Field(..., min_length=1)
    unit_id: str = Field(..., min_length=1)
    title: str = ""
    snippet: str = Field(..., min_length=1)

    score: float | None = None

    jurisdiction: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None

    source_url: str | None = None
    source_doc_id: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


class BlockingIssue(BaseModel):
    key: str | None = None
    severity: SeverityValue = "MEDIUM"
    description: str = Field(..., min_length=1)
    evidence: list[str] = Field(default_factory=list)


class RequiredAction(BaseModel):
    title: str = Field(..., min_length=1)
    why: str | None = None
    how: str | None = None
    due_by: str | None = None
    owner: str | None = None


class ComplianceDecision(BaseModel):
    decision: DecisionValue
    severity: SeverityValue
    confidence: float = Field(..., ge=0.0, le=1.0)

    blocking_issues: list[BlockingIssue] = Field(default_factory=list)
    required_actions: list[RequiredAction] = Field(default_factory=list)

    risks: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

    explainability: dict[str, Any] = Field(default_factory=dict)
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)

