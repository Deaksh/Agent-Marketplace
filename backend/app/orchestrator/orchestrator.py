from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from app.agents.registry import AgentRegistry
from app.db.models import AuditLog, Execution, ExecutionStep, Outcome


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
        return base + [
            PlanStep("regulation_retriever", 1),
            PlanStep("obligation_mapper", 2),
            PlanStep("risk_scorer", 3),
            PlanStep("report_generator", 4),
        ]

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
        agent = self._registry.get(agent_name)
        return await agent.run(intent=intent, context=context, state=state)

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
                    },
                )
            )
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

