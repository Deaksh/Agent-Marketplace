from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import AgentRegistry
from app.agents.marketplace.llm_prompt import LlmPromptMarketplaceAgent
from app.agents.marketplace.remote_http import RemoteHttpMarketplaceAgent
from app.core.config import settings
from app.db.models import (
    AgentPackage,
    AgentVersion,
    AuditLog,
    Execution,
    ExecutionStep,
    OrgAgentEnablement,
    OrgPolicy,
    Outcome,
)
from app.schemas.decision import BlockingIssue, Citation, ComplianceDecision, RequiredAction


def _now() -> datetime:
    return datetime.utcnow()


@dataclass(frozen=True)
class PlanStep:
    agent_name: str
    parallel_group: int = 0  # same group -> run concurrently


class Orchestrator:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        session: AsyncSession,
        validator: Callable[[dict[str, Any]], tuple[float, dict[str, Any]]],
    ) -> None:
        self._registry = registry
        self._session = session
        self._validator = validator

    async def plan(self, *, intent: str, context: dict[str, Any], state: dict[str, Any]) -> list[PlanStep]:
        """
        MVP planner:
        - Always run intent_parser first
        - Then choose a workflow-specific set of steps
        - Designed so we can swap for LLM function-calling planner later
        """
        workflow_hint = (context.get("workflow") or "").strip().lower()
        if workflow_hint:
            state["workflow_hint"] = workflow_hint

        # Always parse intent first to set state["workflow"]/["regulation_code"]/signals.
        base: list[PlanStep] = [PlanStep("intent_parser", 0)]

        # Decide workflow after intent_parser has executed (state may not exist yet here),
        # so default to a safe, general plan; intent_parser can refine downstream behavior.
        # The executor will still run all steps listed for the chosen plan.
        # If the caller explicitly requests a workflow, honor it.
        workflow = workflow_hint or "auto"

        if workflow in {"regulation_lookup"}:
            return base + [PlanStep("regulation_retriever", 1), PlanStep("report_generator", 2)]

        if workflow in {"risk_scoring", "risk_scoring_only"}:
            return base + [PlanStep("obligation_mapper", 1), PlanStep("risk_scorer", 2), PlanStep("report_generator", 3)]

        # Default / auto:
        # - For GDPR we keep the full pipeline.
        # - For other frameworks we still retrieve evidence, then run risk+report (obligation mapper is GDPR-specific today).
        framework = (state.get("framework_code") or context.get("framework_code") or state.get("regulation_code") or "").strip().upper()
        if framework and framework != "GDPR":
            plan = base + [PlanStep("regulation_retriever", 1), PlanStep("risk_scorer", 2), PlanStep("report_generator", 3)]
        else:
            plan = base + [
                PlanStep("regulation_retriever", 1),
                PlanStep("obligation_mapper", 2),
                PlanStep("risk_scorer", 3),
                PlanStep("report_generator", 4),
            ]
        # Insert enabled marketplace agents (parallel) after obligation mapping.
        marketplace_steps = await self._marketplace_plan_steps(context=context)
        if marketplace_steps:
            # run in parallel group 2.5 (we'll use group 25)
            plan = plan[:3] + marketplace_steps + plan[3:]
        return plan

    async def _marketplace_plan_steps(self, *, context: dict[str, Any]) -> list[PlanStep]:
        org_id_raw = context.get("org_id")
        if not org_id_raw:
            return []
        try:
            org_id = UUID(str(org_id_raw))
        except Exception as e:  # noqa: BLE001
            raise ValueError("invalid org_id") from e
        rows = (
            (
                await self._session.execute(
                    select(OrgAgentEnablement).where(OrgAgentEnablement.org_id == org_id).where(OrgAgentEnablement.enabled == True)  # noqa: E712
                )
            )
            .scalars()
            .all()
        )

        policy = (await self._session.execute(select(OrgPolicy).where(OrgPolicy.org_id == org_id))).scalars().first()
        allowed = set(policy.allowed_packages or []) if policy else set()
        blocked = set(policy.blocked_packages or []) if policy else set()

        steps: list[PlanStep] = []
        for r in rows:
            pkg_id_s = str(r.package_id)
            if allowed and pkg_id_s not in allowed:
                continue
            if pkg_id_s in blocked:
                continue
            steps.append(PlanStep(f"marketplace::{r.package_id}", 25))
        return steps

    async def execute(self, *, execution: Execution) -> Outcome:
        execution.status = "running"
        execution.started_at = _now()
        await self._session.merge(execution)
        await self._session.commit()

        state: dict[str, Any] = {}
        audit_trail: list[dict[str, Any]] = []

        plan = await self.plan(intent=execution.intent, context=execution.context, state=state)

        self._session.add(
            AuditLog(
                execution_id=execution.id,
                event_type="execution.started",
                message="Execution started",
                payload={
                    "workflow": execution.workflow,
                    "intent": execution.intent,
                    "context": execution.context,
                    "org_id": str(execution.org_id) if execution.org_id else None,
                    "case_id": str(execution.case_id) if getattr(execution, "case_id", None) else None,
                    "idempotency_key": getattr(execution, "idempotency_key", None),
                },
            )
        )
        await self._session.commit()

        # Create step rows upfront for auditability.
        steps = []
        for idx, s in enumerate(plan):
            step = ExecutionStep(
                execution_id=execution.id,
                step_index=idx,
                agent_name=s.agent_name,
                status="PENDING",
                input={},
                output={},
            )
            self._session.add(step)
            steps.append(step)
        await self._session.commit()

        # Execute step-by-step (supporting future parallel groups)
        grouped: dict[int, list[ExecutionStep]] = {}
        for step_row, plan_step in zip(steps, plan, strict=True):
            grouped.setdefault(plan_step.parallel_group, []).append(step_row)

        try:
            for group in sorted(grouped.keys()):
                await asyncio.gather(
                    *[self._run_step(step_row=sr, execution=execution, state=state, audit=audit_trail) for sr in grouped[group]]
                )

            confidence, explainability = self._validator(state)
            state["confidence"] = confidence
            state["explainability"] = explainability

            decision = self._build_compliance_decision(state=state, audit_trail=audit_trail)
            outcome = Outcome(
                execution_id=execution.id,
                result={
                    "result": state.get("result_text") or "",
                    "confidence": confidence,
                    "risks": state.get("risks") or [],
                    "recommendations": state.get("recommendations") or [],
                    "audit_trail": audit_trail,
                    "explainability": explainability,
                    # New, decision-first schema (kept alongside legacy fields for compatibility).
                    "decision": decision.model_dump(),
                },
                confidence=confidence,
                explainability_trace=explainability,
            )
            self._session.add(outcome)

            execution.status = "succeeded"
            execution.completed_at = _now()
            await self._session.merge(execution)
            self._session.add(
                AuditLog(
                    execution_id=execution.id,
                    event_type="execution.succeeded",
                    message="Execution succeeded",
                    payload={"confidence": confidence},
                )
            )
            await self._session.commit()
            return outcome
        except Exception as e:  # noqa: BLE001
            execution.status = "failed"
            execution.completed_at = _now()
            execution.error = str(e)
            await self._session.merge(execution)
            self._session.add(
                AuditLog(
                    execution_id=execution.id,
                    event_type="execution.failed",
                    message="Execution failed",
                    payload={"error": str(e)},
                )
            )
            await self._session.commit()
            raise

    def _build_compliance_decision(self, *, state: dict[str, Any], audit_trail: list[dict[str, Any]]) -> ComplianceDecision:
        """
        Deterministic decision synthesis from the current MVP state.

        This will become workflow-specific and policy-driven, but is strict + stable today.
        """
        confidence = float(state.get("confidence") or 0.0)
        explainability = state.get("explainability") or {}

        # Evidence check comes from validator when present (report_generator also uses this).
        evidence_ok = True
        checks = explainability.get("checks") or []
        if isinstance(checks, list):
            for c in checks:
                if isinstance(c, dict) and c.get("check") == "evidence_sufficient":
                    evidence_ok = bool(c.get("ok"))
                    break

        risk_score = float(state.get("risk_score") or 0.0)
        risks = state.get("risks") or []
        recommendations = state.get("recommendations") or []
        gaps = state.get("gaps") or []

        citations = self._extract_citations(state=state, audit_trail=audit_trail)

        blocking_issues: list[BlockingIssue] = []
        for g in gaps:
            if not isinstance(g, dict):
                continue
            sev = str(g.get("severity") or "medium").lower()
            sev_norm = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "critical": "CRITICAL"}.get(sev, "MEDIUM")
            blocking_issues.append(
                BlockingIssue(
                    key=g.get("key"),
                    severity=sev_norm,  # type: ignore[arg-type]
                    description=str(g.get("description") or "Unspecified issue"),
                    evidence=[],
                )
            )

        required_actions: list[RequiredAction] = []
        for r in recommendations:
            if not isinstance(r, dict):
                continue
            title = str(r.get("title") or "").strip()
            if not title:
                continue
            required_actions.append(RequiredAction(title=title, why=r.get("why"), how=r.get("how")))

        # Decision logic (MVP but explicit):
        # - Missing citations/evidence => NEEDS_REVIEW (blocks enterprise approvals)
        # - High risk score => NON_COMPLIANT
        # - Otherwise COMPLIANT with actions
        if not evidence_ok or not citations:
            decision_value: str = "NEEDS_REVIEW"
            severity_value: str = "HIGH" if risk_score >= 0.55 else "MEDIUM"
            if not citations:
                blocking_issues.insert(
                    0,
                    BlockingIssue(
                        key="insufficient_citations",
                        severity="HIGH",
                        description="Decision missing required regulatory citations; retrieval evidence is insufficient.",
                        evidence=[],
                    ),
                )
        elif risk_score >= 0.75:
            decision_value = "NON_COMPLIANT"
            severity_value = "HIGH"
        elif risk_score >= 0.55:
            decision_value = "NEEDS_REVIEW"
            severity_value = "MEDIUM"
        else:
            decision_value = "COMPLIANT"
            severity_value = "LOW" if risk_score < 0.35 else "MEDIUM"

        return ComplianceDecision(
            decision=decision_value,  # type: ignore[arg-type]
            severity=severity_value,  # type: ignore[arg-type]
            confidence=max(0.0, min(1.0, confidence)),
            blocking_issues=blocking_issues,
            required_actions=required_actions,
            risks=risks if isinstance(risks, list) else [],
            recommendations=recommendations if isinstance(recommendations, list) else [],
            citations=citations,
            explainability=explainability if isinstance(explainability, dict) else {},
            audit_trail=audit_trail,
        )

    def _extract_citations(self, *, state: dict[str, Any], audit_trail: list[dict[str, Any]]) -> list[Citation]:
        """
        Normalize citations from the regulation retriever output.

        Today, we prefer `state["regulation_snippets"]` and fall back to the audit trail.
        """
        raw_snippets: list[Any] = []
        if isinstance(state.get("regulation_snippets"), list):
            raw_snippets = list(state["regulation_snippets"])  # type: ignore[assignment]
        if not raw_snippets and isinstance(audit_trail, list):
            for ev in audit_trail:
                if isinstance(ev, dict) and ev.get("agent") == "regulation_retriever":
                    out = ev.get("output") if isinstance(ev.get("output"), dict) else {}
                    if isinstance(out.get("snippets"), list):
                        raw_snippets = out["snippets"]
                    break

        citations: list[Citation] = []
        for s in raw_snippets[:20]:
            if not isinstance(s, dict):
                continue
            meta = s.get("metadata") if isinstance(s.get("metadata"), dict) else {}
            # Allow both legacy metadata shape and future normalized fields.
            citation = Citation(
                regulation_code=str(s.get("regulation_code") or meta.get("regulation_code") or "UNKNOWN"),
                unit_id=str(s.get("unit_id") or meta.get("unit_id") or "UNKNOWN"),
                title=str(s.get("title") or ""),
                snippet=str(s.get("text") or s.get("snippet") or "").strip() or "—",
                score=(float(s["score"]) if isinstance(s.get("score"), (int, float)) else None),
                jurisdiction=(meta.get("jurisdiction") if isinstance(meta.get("jurisdiction"), str) else None),
                effective_from=(meta.get("effective_from") if isinstance(meta.get("effective_from"), str) else None),
                effective_to=(meta.get("effective_to") if isinstance(meta.get("effective_to"), str) else None),
                source_url=(meta.get("source_url") if isinstance(meta.get("source_url"), str) else meta.get("source") if isinstance(meta.get("source"), str) else None),
                source_doc_id=(meta.get("source_doc_id") if isinstance(meta.get("source_doc_id"), str) else None),
                source=meta,
            )
            citations.append(citation)
        return citations

    async def _invoke_agent_once(self, *, agent_name: str, intent: str, context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        if agent_name.startswith("marketplace::"):
            package_id = agent_name.split("::", 1)[1]
            return await self._run_marketplace_agent(package_id=package_id, intent=intent, context=context, state=state)
        agent = self._registry.get(agent_name)
        return await agent.run(intent=intent, context=context, state=state)

    def _agent_timeout_s(self, *, agent_name: str) -> float:
        # Marketplace remote agents already have httpx timeouts; we still enforce a hard wall-clock timeout here.
        if agent_name.startswith("marketplace::"):
            return float(settings.marketplace_remote_timeout_s or settings.agent_timeout_s_default)
        return float(settings.agent_timeout_s_default)

    def _fallback_agent(self, *, agent_name: str, context: dict[str, Any]) -> str | None:
        """
        Runtime-configurable fallback chain.

        Caller can pass context:
          fallback_agents: {\"risk_scorer\": \"risk_scorer_v2\"}
        """
        fb = context.get("fallback_agents")
        if isinstance(fb, dict):
            v = fb.get(agent_name)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    async def _run_marketplace_agent(
        self, *, package_id: str, intent: str, context: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        org_id_raw = context.get("org_id")
        if not org_id_raw:
            raise ValueError("org_id required for marketplace agents")
        org_id = UUID(str(org_id_raw))
        pkg_id = UUID(str(package_id))

        policy = (await self._session.execute(select(OrgPolicy).where(OrgPolicy.org_id == org_id))).scalars().first()
        allowed = set(policy.allowed_packages or []) if policy else set()
        blocked = set(policy.blocked_packages or []) if policy else set()
        if allowed and str(pkg_id) not in allowed:
            raise ValueError("agent blocked by org policy (not in allowlist)")
        if str(pkg_id) in blocked:
            raise ValueError("agent blocked by org policy (denylist)")

        enablement = (
            (
                await self._session.execute(
                    select(OrgAgentEnablement)
                    .where(OrgAgentEnablement.org_id == org_id)
                    .where(OrgAgentEnablement.package_id == pkg_id)
                    .where(OrgAgentEnablement.enabled == True)  # noqa: E712
                )
            )
            .scalars()
            .first()
        )
        if not enablement:
            raise ValueError("agent not enabled for org")
        version: AgentVersion | None = None
        if enablement.pinned_version_id:
            version = (await self._session.execute(select(AgentVersion).where(AgentVersion.id == enablement.pinned_version_id))).scalars().first()
            if version and version.package_id != pkg_id:
                raise ValueError("pinned_version_id does not belong to this package")
        if not version:
            version = (
                (await self._session.execute(select(AgentVersion).where(AgentVersion.package_id == pkg_id).order_by(AgentVersion.created_at.desc())))
                .scalars()
                .first()
            )
        if not version:
            raise ValueError("no agent version found")

        if version.status != "active":
            raise ValueError("agent version is not active")

        # Certification gating: require VERIFIED for case-linked executions.
        if context.get("case_id") and (version.cert_status or "").upper() != "VERIFIED":
            raise ValueError("agent version not VERIFIED for case execution")

        # Basic cost guardrail (policy hook later).
        if version.cost_estimate_usd and version.cost_estimate_usd > float(settings.marketplace_max_cost_usd):
            raise ValueError("agent cost estimate exceeds max cost guardrail")

        pkg = (await self._session.execute(select(AgentPackage).where(AgentPackage.id == version.package_id))).scalars().first()
        name = f"marketplace.{pkg.slug if pkg else package_id}"
        description = (pkg.description if pkg else "Marketplace agent").strip() or "Marketplace agent"

        if version.runtime == "remote_http":
            if not version.endpoint_url:
                raise ValueError("endpoint_url required for remote_http runtime")
            agent = RemoteHttpMarketplaceAgent(
                name=name,
                description=description,
                endpoint_url=version.endpoint_url,
                input_schema=version.input_schema,
                output_schema=version.output_schema,
                cost_estimate_usd=version.cost_estimate_usd,
                reliability_score=version.reliability_score,
                timeout_s=settings.marketplace_remote_timeout_s,
            )
            out = await agent.run(intent=intent, context=context, state=state)
        elif version.runtime == "llm_prompt":
            if not version.prompt_template:
                raise ValueError("prompt_template required for llm_prompt runtime")
            agent = LlmPromptMarketplaceAgent(
                name=name,
                description=description,
                prompt_template=version.prompt_template,
                input_schema=version.input_schema,
                output_schema=version.output_schema,
                cost_estimate_usd=version.cost_estimate_usd,
                reliability_score=version.reliability_score,
            )
            out = await agent.run(intent=intent, context=context, state=state)
        elif version.runtime == "builtin":
            if not version.builtin_agent_name:
                raise ValueError("builtin_agent_name required for builtin runtime")
            out = await self._registry.get(version.builtin_agent_name).run(intent=intent, context=context, state=state)
        else:
            raise ValueError("unknown marketplace runtime")

        # Store in state under a namespaced key.
        state.setdefault("marketplace_outputs", []).append(
            {"package_id": str(pkg_id), "version_id": str(version.id), "runtime": version.runtime, "output": out}
        )
        # Return output with attached meta for provenance.
        return {"__marketplace": {"package_id": str(pkg_id), "version_id": str(version.id), "runtime": version.runtime}, "output": out}

    async def _run_step(
        self,
        *,
        step_row: ExecutionStep,
        execution: Execution,
        state: dict[str, Any],
        audit: list[dict[str, Any]],
    ) -> None:
        step_row.status = "RUNNING"
        step_row.started_at = _now()
        step_row.attempts += 1
        step_row.input = {
            "intent": execution.intent,
            "context": execution.context,
            "state_keys": sorted(list(state.keys())),
        }
        await self._session.merge(step_row)
        self._session.add(
            AuditLog(
                execution_id=execution.id,
                step_id=step_row.id,
                event_type="step.started",
                message=f"Step started: {step_row.agent_name}",
                payload={
                    "step_index": step_row.step_index,
                    "agent": step_row.agent_name,
                    "attempts": step_row.attempts,
                    "input": step_row.input,
                    "agent_package_id": str(step_row.agent_package_id) if step_row.agent_package_id else None,
                    "agent_version_id": str(step_row.agent_version_id) if step_row.agent_version_id else None,
                },
            )
        )
        await self._session.commit()

        try:
            output = None
            last_err: Exception | None = None
            max_attempts = max(1, int(settings.agent_retry_attempts or 1))
            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        step_row.status = "RETRIED"
                        await self._session.merge(step_row)
                        self._session.add(
                            AuditLog(
                                execution_id=execution.id,
                                step_id=step_row.id,
                                event_type="step.retried",
                                message=f"Step retrying ({attempt}/{max_attempts}): {step_row.agent_name}",
                                payload={"attempt": attempt, "max_attempts": max_attempts, "agent": step_row.agent_name},
                            )
                        )
                        await self._session.commit()

                    timeout_s = self._agent_timeout_s(agent_name=step_row.agent_name)
                    output = await asyncio.wait_for(
                        self._invoke_agent_once(
                            agent_name=step_row.agent_name,
                            intent=execution.intent,
                            context=execution.context,
                            state=state,
                        ),
                        timeout=timeout_s,
                    )
                    last_err = None
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    if attempt >= max_attempts:
                        break
                    backoff = min(
                        float(settings.agent_retry_backoff_max_s),
                        float(settings.agent_retry_backoff_initial_s) * (2 ** (attempt - 1)),
                    )
                    # jitter
                    await asyncio.sleep(backoff * (0.7 + 0.6 * random.random()))

            if last_err:
                fb = self._fallback_agent(agent_name=step_row.agent_name, context=execution.context)
                if fb:
                    self._session.add(
                        AuditLog(
                            execution_id=execution.id,
                            step_id=step_row.id,
                            event_type="step.fallback",
                            message=f"Falling back from {step_row.agent_name} to {fb}",
                            payload={"from": step_row.agent_name, "to": fb, "error": str(last_err)},
                        )
                    )
                    await self._session.commit()
                    timeout_s = self._agent_timeout_s(agent_name=fb)
                    output = await asyncio.wait_for(
                        self._invoke_agent_once(agent_name=fb, intent=execution.intent, context=execution.context, state=state),
                        timeout=timeout_s,
                    )
                else:
                    raise last_err

            marketplace_meta = None
            if isinstance(output, dict) and "__marketplace" in output:
                marketplace_meta = output.get("__marketplace")
                # Keep the actual agent output clean.
                output = output.get("output") if isinstance(output.get("output"), dict) else {"output": output.get("output")}
                if isinstance(marketplace_meta, dict):
                    try:
                        step_row.agent_package_id = UUID(str(marketplace_meta.get("package_id")))
                        step_row.agent_version_id = UUID(str(marketplace_meta.get("version_id")))
                    except Exception:  # noqa: BLE001
                        pass
            step_row.status = "SUCCESS"
            step_row.completed_at = _now()
            step_row.output = output or {}
            await self._session.merge(step_row)
            self._session.add(
                AuditLog(
                    execution_id=execution.id,
                    step_id=step_row.id,
                    event_type="step.succeeded",
                    message=f"Step succeeded: {step_row.agent_name}",
                    payload={
                        "step_index": step_row.step_index,
                        "agent": step_row.agent_name,
                        "attempts": step_row.attempts,
                        "output": step_row.output,
                        "agent_package_id": str(step_row.agent_package_id) if step_row.agent_package_id else None,
                        "agent_version_id": str(step_row.agent_version_id) if step_row.agent_version_id else None,
                    },
                )
            )
            await self._session.commit()

            # Update minimal marketplace stats if this step was a marketplace agent.
            if step_row.agent_version_id and step_row.started_at and step_row.completed_at:
                v = (
                    (await self._session.execute(select(AgentVersion).where(AgentVersion.id == step_row.agent_version_id)))
                    .scalars()
                    .first()
                )
                if v:
                    latency_ms = (step_row.completed_at - step_row.started_at).total_seconds() * 1000.0
                    v.run_count += 1
                    v.success_count += 1
                    # EWMA-ish average
                    v.avg_latency_ms = (v.avg_latency_ms * 0.8) + (latency_ms * 0.2) if v.avg_latency_ms else latency_ms
                    await self._session.merge(v)
                    await self._session.commit()

            audit.append(
                {
                    "step_index": step_row.step_index,
                    "agent": step_row.agent_name,
                    "input": step_row.input,
                    "output": step_row.output,
                    "status": step_row.status,
                    "started_at": step_row.started_at.isoformat() if step_row.started_at else None,
                    "completed_at": step_row.completed_at.isoformat() if step_row.completed_at else None,
                    "attempts": step_row.attempts,
                }
            )
        except Exception as e:  # noqa: BLE001
            step_row.status = "FAILED"
            step_row.completed_at = _now()
            step_row.error = str(e)
            await self._session.merge(step_row)
            self._session.add(
                AuditLog(
                    execution_id=execution.id,
                    step_id=step_row.id,
                    event_type="step.failed",
                    message=f"Step failed: {step_row.agent_name}",
                    payload={
                        "step_index": step_row.step_index,
                        "agent": step_row.agent_name,
                        "attempts": step_row.attempts,
                        "error": str(e),
                    },
                )
            )
            await self._session.commit()

            if step_row.agent_version_id:
                v = (
                    (await self._session.execute(select(AgentVersion).where(AgentVersion.id == step_row.agent_version_id)))
                    .scalars()
                    .first()
                )
                if v:
                    v.run_count += 1
                    await self._session.merge(v)
                    await self._session.commit()
            audit.append(
                {
                    "step_index": step_row.step_index,
                    "agent": step_row.agent_name,
                    "status": "failed",
                    "error": str(e),
                    "attempts": step_row.attempts,
                }
            )
            raise

