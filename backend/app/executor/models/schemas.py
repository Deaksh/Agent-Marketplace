from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


DecisionValue = Literal["COMPLIANT", "NON_COMPLIANT", "PARTIAL"]


class RunRequest(BaseModel):
    task_id: str = Field(..., min_length=1)


class RunResponse(BaseModel):
    status: Literal["completed", "failed"]
    decision: DecisionValue
    summary: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class WatchtowerTask(BaseModel):
    id: str
    regulation_id: str | None = None
    regulation_version_id: str | None = None
    model_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class WatchtowerRegulation(BaseModel):
    id: str
    text: str | None = None
    units: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class WatchtowerModel(BaseModel):
    id: str
    description: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class AnalysisInput(BaseModel):
    regulation_text: str
    model_description: str
    task_context: str


class AnalysisResult(BaseModel):
    decision: DecisionValue
    summary: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: dict[str, Any] = Field(default_factory=dict)

