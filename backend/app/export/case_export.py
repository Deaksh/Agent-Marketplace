from __future__ import annotations

import io
from typing import Any
from uuid import UUID

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentPackage, AgentVersion, AuditLog, ComplianceCase, Execution, ExecutionStep, Outcome


async def build_case_export(*, session: AsyncSession, case_id: UUID) -> dict[str, Any]:
    case = (await session.execute(select(ComplianceCase).where(ComplianceCase.id == case_id))).scalars().first()
    if not case:
        raise ValueError("case not found")

    executions = (
        (await session.execute(select(Execution).where(Execution.case_id == case_id).order_by(Execution.created_at.asc())))
        .scalars()
        .all()
    )

    exec_ids = [e.id for e in executions]
    outcomes = (
        (await session.execute(select(Outcome).where(Outcome.execution_id.in_(exec_ids))))  # type: ignore[arg-type]
        .scalars()
        .all()
        if exec_ids
        else []
    )
    outcome_by_exec = {o.execution_id: o for o in outcomes}

    steps = (
        (await session.execute(select(ExecutionStep).where(ExecutionStep.execution_id.in_(exec_ids))))  # type: ignore[arg-type]
        .scalars()
        .all()
        if exec_ids
        else []
    )

    pkg_ids = {s.agent_package_id for s in steps if s.agent_package_id}
    ver_ids = {s.agent_version_id for s in steps if s.agent_version_id}
    packages = (
        (await session.execute(select(AgentPackage).where(AgentPackage.id.in_(pkg_ids))))  # type: ignore[arg-type]
        .scalars()
        .all()
        if pkg_ids
        else []
    )
    versions = (
        (await session.execute(select(AgentVersion).where(AgentVersion.id.in_(ver_ids))))  # type: ignore[arg-type]
        .scalars()
        .all()
        if ver_ids
        else []
    )
    pkg_by_id = {p.id: p for p in packages}
    ver_by_id = {v.id: v for v in versions}

    audit_rows = (
        (await session.execute(select(AuditLog).where(AuditLog.execution_id.in_(exec_ids)).order_by(AuditLog.created_at)))  # type: ignore[arg-type]
        .scalars()
        .all()
        if exec_ids
        else []
    )

    execution_exports: list[dict[str, Any]] = []
    for e in executions:
        outcome = outcome_by_exec.get(e.id)
        payload = (outcome.result if outcome else {}) or {}
        decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else None
        if not decision and outcome:
            # Prefer persisted decision-first columns when present.
            decision = {
                "decision": getattr(outcome, "decision", None),
                "severity": getattr(outcome, "severity", None),
                "confidence": getattr(outcome, "confidence", None),
                "risk_score": getattr(outcome, "risk_score", None),
                "blocking_issues": getattr(outcome, "decision_blocking_issues", []) or [],
                "required_actions": getattr(outcome, "decision_required_actions", []) or [],
                "risks": getattr(outcome, "decision_risks", []) or [],
                "recommendations": getattr(outcome, "decision_recommendations", []) or [],
                "citations": getattr(outcome, "decision_citations", []) or [],
                "explainability": getattr(outcome, "decision_explainability", {}) or {},
                "metadata": {
                    "decision_version": getattr(outcome, "decision_version", None),
                    "generated_at": (getattr(outcome, "decision_generated_at", None).isoformat() if getattr(outcome, "decision_generated_at", None) else None),
                },
            }

        e_steps = [s for s in steps if s.execution_id == e.id]
        e_steps.sort(key=lambda s: s.step_index)
        step_exports = []
        for s in e_steps:
            pkg = pkg_by_id.get(s.agent_package_id) if s.agent_package_id else None
            ver = ver_by_id.get(s.agent_version_id) if s.agent_version_id else None
            step_exports.append(
                {
                    "id": str(s.id),
                    "step_index": s.step_index,
                    "agent_name": s.agent_name,
                    "status": s.status,
                    "attempts": s.attempts,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                    "error": s.error,
                    "agent_package": (
                        {"id": str(pkg.id), "publisher": pkg.publisher, "slug": pkg.slug, "name": pkg.name} if pkg else None
                    ),
                    "agent_version": (
                        {
                            "id": str(ver.id),
                            "version": ver.version,
                            "runtime": ver.runtime,
                            "builtin_agent_name": ver.builtin_agent_name,
                            "cert_status": getattr(ver, "cert_status", None),
                        }
                        if ver
                        else None
                    ),
                }
            )

        e_audit = [a for a in audit_rows if a.execution_id == e.id]
        audit_exports = [
            {
                "id": str(a.id),
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "event_type": a.event_type,
                "message": a.message,
                "step_id": str(a.step_id) if a.step_id else None,
                "payload": a.payload,
            }
            for a in e_audit
        ]

        execution_exports.append(
            {
                "execution_id": str(e.id),
                "workflow": e.workflow,
                "intent": e.intent,
                "status": e.status,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
                "error": e.error,
                "decision": decision,
                "outcome": payload,
                "steps": step_exports,
                "audit": audit_exports,
            }
        )

    # Case-level final decision preference:
    # - explicit case.final_decision if present
    # - else most recent execution decision if present
    final_decision = case.final_decision
    if not final_decision:
        for ex in reversed(execution_exports):
            if isinstance(ex.get("decision"), dict):
                final_decision = ex["decision"]
                break

    return {
        "case": {
            "case_id": str(case.id),
            "org_id": str(case.org_id) if case.org_id else None,
            "owner_id": case.owner_id,
            "title": case.title,
            "description": case.description,
            "system_name": getattr(case, "system_name", ""),
            "system_description": getattr(case, "system_description", ""),
            "use_case_type": getattr(case, "use_case_type", ""),
            "deployment_region": getattr(case, "deployment_region", ""),
            "data_types": getattr(case, "data_types", []) or [],
            "reviewer_ids": getattr(case, "reviewer_ids", []) or [],
            "decision_status": getattr(case, "decision_status", None),
            "status": case.status,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
            "finalized_at": case.finalized_at.isoformat() if case.finalized_at else None,
        },
        "final_decision": final_decision,
        "executions": execution_exports,
    }


def render_case_export_pdf(*, export: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    width, height = LETTER
    x = 54
    y = height - 54

    def line(txt: str, dy: float = 14) -> None:
        nonlocal y
        if y < 72:
            c.showPage()
            y = height - 54
        c.drawString(x, y, txt[:160])
        y -= dy

    case = export.get("case") or {}
    decision = export.get("final_decision") or {}

    c.setFont("Helvetica-Bold", 16)
    line("Compliance Evidence Pack", dy=22)
    c.setFont("Helvetica", 10)
    line(f"Case: {case.get('title') or ''}")
    line(f"Case ID: {case.get('case_id') or ''}")
    line(f"Status: {case.get('status') or ''}")
    line(f"Owner: {case.get('owner_id') or ''}")
    if case.get("system_name"):
        line(f"System: {case.get('system_name')}")
    if case.get("use_case_type"):
        line(f"System type: {case.get('use_case_type')}")
    if case.get("deployment_region"):
        line(f"Region: {case.get('deployment_region')}")
    dts = case.get("data_types")
    if isinstance(dts, list) and dts:
        line(f"Data types: {', '.join([str(x) for x in dts][:8])}")
    line("")

    c.setFont("Helvetica-Bold", 12)
    line("Decision", dy=18)
    c.setFont("Helvetica", 10)
    line(f"Decision: {decision.get('decision') or '—'}")
    line(f"Severity: {decision.get('severity') or '—'}")
    line(f"Confidence: {decision.get('confidence') if decision else '—'}")
    if decision.get("risk_score") is not None:
        line(f"Risk score: {decision.get('risk_score')}")
    line("")

    blocking = decision.get("blocking_issues") if isinstance(decision, dict) else None
    if isinstance(blocking, list) and blocking:
        c.setFont("Helvetica-Bold", 12)
        line("Blocking Issues", dy=18)
        c.setFont("Helvetica", 10)
        for bi in blocking[:12]:
            if not isinstance(bi, dict):
                continue
            line(f"- [{bi.get('severity')}] {bi.get('description')}")
        line("")

    citations = decision.get("citations") if isinstance(decision, dict) else None
    if isinstance(citations, list) and citations:
        c.setFont("Helvetica-Bold", 12)
        line("Regulatory Citations", dy=18)
        c.setFont("Helvetica", 10)
        for ci in citations[:15]:
            if not isinstance(ci, dict):
                continue
            # Support both legacy and DecisionV1 citation shapes.
            reg = ci.get("regulation") or ci.get("regulation_code")
            art = ci.get("article") or ci.get("unit_id")
            line(f"- {reg} {art}".strip())
            snippet = str(ci.get("text_snippet") or ci.get("snippet") or "").replace("\n", " ").strip()
            if snippet:
                line(f"  {snippet[:140]}", dy=12)
        line("")

    c.setFont("Helvetica-Bold", 12)
    line("Executions", dy=18)
    c.setFont("Helvetica", 10)
    for ex in (export.get("executions") or [])[:10]:
        if not isinstance(ex, dict):
            continue
        line(f"- {ex.get('execution_id')}  status={ex.get('status')}  workflow={ex.get('workflow')}")

    c.showPage()
    c.save()
    return buf.getvalue()

