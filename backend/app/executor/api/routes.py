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
    b = base_url.rstrip("/")
    return (
        f"Cannot reach Watchtower at {b}. ({detail}) "
        "Check: Watchtower uvicorn is running; port 8000 is forwarded and Public on that Codespace; URL matches the Ports panel. "
        f'Debug from this VM: curl -v "{b}/tasks/TASK_123" '
        "(expect HTTP 200 JSON, not 404 HTML—if 404, your EXECUTOR_WATCHTOWER_BASE_URL path prefix is wrong)."
    )


def _http_error_summary(exc: httpx.HTTPStatusError) -> str:
    req_url = str(exc.request.url)
    body = (exc.response.text or "").strip().replace("\n", " ")[:400]
    return (
        f"Watchtower returned HTTP {exc.response.status_code} for {req_url}. "
        f"Fix the URL path or task id. Response preview: {body or '—'}"
    )


@router.post("/run", response_model=RunResponse)
async def run(req: RunRequest) -> RunResponse:
    base = executor_settings.watchtower_base_url
    try:
        result = await run_task(task_id=req.task_id)
        return RunResponse(status="completed", decision=result.decision, summary=result.summary, confidence=result.confidence)
    except httpx.HTTPStatusError as e:
        logger.warning("run_http_failed task_id=%s status=%s url=%s", req.task_id, e.response.status_code, e.request.url)
        return RunResponse(
            status="failed",
            decision="PARTIAL",
            summary=_http_error_summary(e),
            confidence=0.0,
        )
    except httpx.ConnectError as e:
        logger.warning("run_connect_failed task_id=%s base=%s err=%s", req.task_id, base, e)
        return RunResponse(
            status="failed",
            decision="PARTIAL",
            summary=_cross_machine_connect_hint(base_url=base, detail=str(e)),
            confidence=0.0,
        )
    except httpx.RequestError as e:
        logger.warning("run_request_failed task_id=%s base=%s err=%s", req.task_id, base, e)
        return RunResponse(
            status="failed",
            decision="PARTIAL",
            summary=f"Watchtower request error ({type(e).__name__}): {e}. Base URL: {base.rstrip('/')}",
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

