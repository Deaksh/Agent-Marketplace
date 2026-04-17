from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

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
    Outcome,
)


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

        # Default / auto: full compliance check.
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
        steps: list[PlanStep] = []
        for r in rows:
            steps.append(PlanStep(f"marketplace::{r.package_id}", 25))
        return steps

    async def execute(self, *, execution: Execution) -> Outcome:
        execution.status = "running"
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
                payload={"workflow": execution.workflow, "intent": execution.intent, "context": execution.context},
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
                status="queued",
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

            outcome = Outcome(
                execution_id=execution.id,
                result={
                    "result": state.get("result_text") or "",
                    "confidence": confidence,
                    "risks": state.get("risks") or [],
                    "recommendations": state.get("recommendations") or [],
                    "audit_trail": audit_trail,
                    "explainability": explainability,
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

    @retry(stop=stop_after_attempt(2), wait=wait_exponential_jitter(initial=0.25, max=2.0))
    async def _invoke_agent(self, *, agent_name: str, intent: str, context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        if agent_name.startswith("marketplace::"):
            package_id = agent_name.split("::", 1)[1]
            return await self._run_marketplace_agent(package_id=package_id, intent=intent, context=context, state=state)
        agent = self._registry.get(agent_name)
        return await agent.run(intent=intent, context=context, state=state)

    async def _run_marketplace_agent(
        self, *, package_id: str, intent: str, context: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        org_id_raw = context.get("org_id")
        if not org_id_raw:
            raise ValueError("org_id required for marketplace agents")
        org_id = UUID(str(org_id_raw))
        pkg_id = UUID(str(package_id))
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
        if not version:
            version = (
                (await self._session.execute(select(AgentVersion).where(AgentVersion.package_id == pkg_id).order_by(AgentVersion.created_at.desc())))
                .scalars()
                .first()
            )
        if not version:
            raise ValueError("no agent version found")

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
        step_row.status = "running"
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
            output = await self._invoke_agent(
                agent_name=step_row.agent_name,
                intent=execution.intent,
                context=execution.context,
                state=state,
            )
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
            step_row.status = "succeeded"
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
            step_row.status = "failed"
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

