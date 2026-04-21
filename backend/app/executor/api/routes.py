from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter

from app.executor.config.settings import executor_settings
from app.executor.models.schemas import RunRequest, RunResponse
from app.executor.services.runner import run_task


logger = logging.getLogger("executor")

router = APIRouter()


def _cross_machine_connect_hint(*, base_url: str, detail: str) -> str:
    return (
        f"Cannot reach Watchtower at {base_url.rstrip('/')}. ({detail}) "
        "If this API runs in GitHub Codespaces (or another remote host) while Watchtower runs on your laptop "
        "(e.g. PyCharm on port 8000), then 127.0.0.1 inside the API process is the remote VM—not your PC. "
        "Run Watchtower in the same environment as the API, or tunnel your local port (ngrok, cloudflared) and set "
        "EXECUTOR_WATCHTOWER_BASE_URL to that public URL (including the path, e.g. …/api/execution)."
    )


@router.post("/run", response_model=RunResponse)
async def run(req: RunRequest) -> RunResponse:
    base = executor_settings.watchtower_base_url
    try:
        result = await run_task(task_id=req.task_id)
        return RunResponse(status="completed", decision=result.decision, summary=result.summary, confidence=result.confidence)
    except httpx.ConnectError as e:
        logger.warning("run_connect_failed task_id=%s base=%s err=%s", req.task_id, base, e)
        return RunResponse(
            status="failed",
            decision="PARTIAL",
            summary=_cross_machine_connect_hint(base_url=base, detail=str(e)),
            confidence=0.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("run_failed task_id=%s", req.task_id)
        # Spec: never crash the server. Return a failed response instead.
        return RunResponse(
            status="failed",
            decision="PARTIAL",
            summary=f"Execution failed: {str(e)}",
            confidence=0.0,
        )

