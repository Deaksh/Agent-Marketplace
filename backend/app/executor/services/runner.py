from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.executor.config.settings import executor_settings
from app.executor.models.schemas import AnalysisInput, AnalysisResult, WatchtowerModel, WatchtowerRegulation, WatchtowerTask
from app.executor.services.analyzer import run_compliance_analysis
from app.executor.services.fetcher import fetch_model, fetch_regulation, fetch_task, post_result


logger = logging.getLogger("executor")


def _watchtower_client_trust_env(base_url: str) -> bool:
    """
    Loopback HTTP often breaks when HTTP(S)_PROXY is set; public HTTPS (e.g. Codespaces
    *.app.github.dev) may need env trust for proxies/custom CA bundles.
    """
    u = base_url.strip().lower()
    if u.startswith("http://127.0.0.1") or u.startswith("http://localhost"):
        return False
    return True


def _task_context_str(ctx: dict[str, Any]) -> str:
    parts: list[str] = []
    for k, v in sorted(ctx.items(), key=lambda kv: kv[0]):
        if v is None:
            continue
        parts.append(f"{k}: {v}")
    return "\n".join(parts)


async def run_task(*, task_id: str) -> AnalysisResult:
    logger.info(
        "task_received task_id=%s watchtower_base=%s",
        task_id,
        executor_settings.watchtower_base_url.rstrip("/"),
    )
    timeout = httpx.Timeout(executor_settings.http_timeout_s)
    trust = _watchtower_client_trust_env(executor_settings.watchtower_base_url)
    async with httpx.AsyncClient(timeout=timeout, trust_env=trust) as client:
        task_raw = await fetch_task(task_id=task_id, client=client)
        task = WatchtowerTask.model_validate(task_raw)
        logger.info("task_fetched task_id=%s regulation_id=%s model_id=%s", task_id, task.regulation_id, task.model_id)

        if not task.regulation_id and not task.regulation_version_id:
            raise ValueError("task missing regulation_id/regulation_version_id")
        if not task.model_id:
            raise ValueError("task missing model_id")

        regulation_id = task.regulation_id or task.regulation_version_id or ""
        reg_raw = await fetch_regulation(regulation_id=regulation_id, client=client)
        regulation = WatchtowerRegulation.model_validate(reg_raw)

        model_raw = await fetch_model(model_id=task.model_id, client=client)
        model = WatchtowerModel.model_validate(model_raw)

        reg_text = (regulation.text or "").strip()
        if not reg_text and regulation.units:
            reg_text = "\n\n".join([str(u.get("text") or "") for u in regulation.units if isinstance(u, dict) and u.get("text")])

        input_data = AnalysisInput(
            regulation_text=reg_text,
            model_description=(model.description or "").strip(),
            task_context=_task_context_str(task.context or {}),
        )

        logger.info("analysis_started task_id=%s", task_id)
        result = await run_compliance_analysis(input_data=input_data)
        logger.info("analysis_completed task_id=%s decision=%s confidence=%.2f", task_id, result.decision, result.confidence)

        payload = {
            "decision": result.decision,
            "summary": result.summary,
            "evidence": result.evidence,
            "confidence": result.confidence,
        }

        last_err: Exception | None = None
        for attempt in range(1, int(executor_settings.result_post_retry_attempts) + 1):
            try:
                await post_result(task_id=task_id, payload=payload, client=client)
                logger.info("result_posted task_id=%s attempt=%s", task_id, attempt)
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.warning("result_post_failed task_id=%s attempt=%s error=%s", task_id, attempt, str(e))
                if attempt < int(executor_settings.result_post_retry_attempts):
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        if last_err:
            raise last_err

        return result

