from __future__ import annotations

import logging

from fastapi import APIRouter

from app.executor.models.schemas import RunRequest, RunResponse
from app.executor.services.runner import run_task


logger = logging.getLogger("executor")

router = APIRouter()


@router.post("/run", response_model=RunResponse)
async def run(req: RunRequest) -> RunResponse:
    try:
        result = await run_task(task_id=req.task_id)
        return RunResponse(status="completed", decision=result.decision, summary=result.summary, confidence=result.confidence)
    except Exception as e:  # noqa: BLE001
        logger.exception("run_failed task_id=%s", req.task_id)
        # Spec: never crash the server. Return a failed response instead.
        return RunResponse(
            status="failed",
            decision="PARTIAL",
            summary=f"Execution failed: {str(e)}",
            confidence=0.0,
        )

