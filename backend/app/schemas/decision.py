from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DecisionValue = Literal["COMPLIANT", "NON_COMPLIANT", "NEEDS_REVIEW"]
SeverityValue = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class CitationV1(BaseModel):
    regulation: str = Field(..., min_length=1)
    article: str = Field(..., min_length=1)
    text_snippet: str = Field(..., min_length=1)
    relevance_score: float = Field(..., ge=0.0, le=1.0)


class ExplainabilityV1(BaseModel):
    reasoning_steps: list[Any] = Field(default_factory=list)


class DecisionMetadataV1(BaseModel):
    decision_version: Literal["v1"] = "v1"
    generated_at: datetime


class DecisionV1(BaseModel):
    """
    Decision-first artifact (strict) produced by every execution.

    This schema is versioned and intended to be regulator/auditor friendly.
    """

    decision: DecisionValue
    severity: SeverityValue
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_score: float = Field(..., ge=0.0, le=1.0)

    blocking_issues: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    citations: list[CitationV1] = Field(default_factory=list)
    explainability: ExplainabilityV1 = Field(default_factory=ExplainabilityV1)
    metadata: DecisionMetadataV1


# Backwards-compatible aliases for older exports/state; keep until frontend migrates fully.
ComplianceDecision = DecisionV1
Citation = CitationV1
BlockingIssue = Any
RequiredAction = Any

