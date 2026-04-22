from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.executor.config.settings import executor_settings
from app.executor.models.schemas import AnalysisInput, AnalysisResult, WatchtowerModel, WatchtowerRegulation, WatchtowerTask
from app.executor.services.analyzer import run_compliance_analysis
from app.executor.services.fetcher import fetch_model, fetch_regulation, fetch_task, fetch_task_events, post_result


logger = logging.getLogger("executor")


def _watchtower_default_headers() -> dict[str, str]:
    key = (executor_settings.watchtower_api_key or "").strip()
    if not key:
        return {}
    name = (executor_settings.watchtower_api_key_header or "X-Admin-Api-Key").strip()
    return {name: key}


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

def _coalesce(*vals: Any) -> str | None:
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        return str(v)
    return None


def _derive_task_refs(task_raw: dict[str, Any], task: WatchtowerTask) -> tuple[str | None, str | None]:
    """
    Beacon task objects may not use `regulation_id` / `model_id`.
    Try common alternative keys so the executor can still run.
    """
    ctx = task.context or {}
    reg_obj = task_raw.get("regulation") if isinstance(task_raw, dict) else None
    if not isinstance(reg_obj, dict):
        reg_obj = None

    regulation_id = _coalesce(
        task.regulation_id,
        task.regulation_version_id,
        task_raw.get("regulation_id"),
        task_raw.get("regulation_version_id"),
        (reg_obj.get("id") if reg_obj else None),
        (reg_obj.get("short_code") if reg_obj else None),
        task_raw.get("regulation"),  # sometimes a code string
        task_raw.get("regulation_code"),
        task_raw.get("source_regulation"),
        ctx.get("regulation_id"),
        ctx.get("regulation_version_id"),
        ctx.get("regulation"),
        ctx.get("regulation_code"),
    )
    model_id = _coalesce(
        task.model_id,
        task_raw.get("model_id"),
        task_raw.get("company_model_id"),
        task_raw.get("model"),
        ctx.get("model_id"),
        ctx.get("company_model_id"),
        ctx.get("model"),
    )
    return regulation_id, model_id


def _derive_refs_from_events(events_raw: Any) -> tuple[str | None, str | None]:
    """
    Beacon tasks may keep useful identifiers in /tasks/{id}/events.
    Try to extract regulation/model identifiers from common shapes.
    """
    rows: list[Any] = []
    if isinstance(events_raw, list):
        rows = events_raw
    elif isinstance(events_raw, dict):
        for k in ("events", "items", "data", "results"):
            v = events_raw.get(k)
            if isinstance(v, list):
                rows = v
                break
        if not rows:
            rows = [events_raw]

    reg: str | None = None
    model: str | None = None
    for ev in rows:
        if not isinstance(ev, dict):
            continue
        payload = ev.get("payload")
        if isinstance(payload, dict):
            reg = reg or _coalesce(payload.get("regulation_id"), payload.get("regulation_code"), payload.get("regulation"))
            model = model or _coalesce(payload.get("model_id"), payload.get("company_model_id"), payload.get("model"))
        reg = reg or _coalesce(ev.get("regulation_id"), ev.get("regulation_code"), ev.get("regulation"))
        model = model or _coalesce(ev.get("model_id"), ev.get("company_model_id"), ev.get("model"))
        if reg and model:
            break
    return reg, model


async def run_task(*, task_id: str) -> AnalysisResult:
    logger.info(
        "task_received task_id=%s watchtower_base=%s",
        task_id,
        executor_settings.watchtower_base_url.rstrip("/"),
    )
    if executor_settings.dev_mock_watchtower:
        logger.warning("EXECUTOR_DEV_MOCK_WATCHTOWER=1 — skipping Beacon HTTP (dev only)")
        return await run_compliance_analysis(
            input_data=AnalysisInput(
                regulation_text=(
                    "(dev mock) Lawfulness, fairness and transparency; purpose limitation; "
                    "data minimization; accuracy; storage limitation; integrity and confidentiality (GDPR-style)."
                ),
                model_description="(dev mock) System that processes personal data for operational decisions.",
                task_context=f"task_id={task_id}",
            )
        )

    timeout = httpx.Timeout(executor_settings.http_timeout_s)
    trust = _watchtower_client_trust_env(executor_settings.watchtower_base_url)
    headers = _watchtower_default_headers()
    async with httpx.AsyncClient(timeout=timeout, trust_env=trust, headers=headers) as client:
        task_raw = await fetch_task(task_id=task_id, client=client)
        task = WatchtowerTask.model_validate(task_raw)
        regulation_id, model_id = _derive_task_refs(task_raw, task)
        if not regulation_id or not model_id:
            try:
                events_raw = await fetch_task_events(task_id=task_id, client=client)
                ev_reg, ev_model = _derive_refs_from_events(events_raw)
                regulation_id = regulation_id or ev_reg
                model_id = model_id or ev_model
            except Exception as e:  # noqa: BLE001
                logger.info("task_events_unavailable task_id=%s error=%s", task_id, str(e))
        logger.info("task_fetched task_id=%s regulation_id=%s model_id=%s", task_id, regulation_id, model_id)

        regulation: WatchtowerRegulation | None = None
        model: WatchtowerModel | None = None

        if regulation_id:
            reg_raw = await fetch_regulation(regulation_id=regulation_id, client=client)
            regulation = WatchtowerRegulation.model_validate(reg_raw)

        if model_id:
            try:
                model_raw = await fetch_model(model_id=model_id, client=client)
                model = WatchtowerModel.model_validate(model_raw)
            except Exception as e:  # noqa: BLE001
                logger.info("model_fetch_failed model_id=%s error=%s", model_id, str(e))
                model = WatchtowerModel.model_validate({"id": model_id, "description": ""})

        reg_text = ((regulation.text if regulation else "") or "").strip()
        if regulation and not reg_text and regulation.units:
            reg_text = "\n\n".join([str(u.get("text") or "") for u in regulation.units if isinstance(u, dict) and u.get("text")])

        input_data = AnalysisInput(
            regulation_text=reg_text,
            model_description=(
                (
                    ((model.description if model else "") or "").strip()
                    or " | ".join(
                        [
                            s
                            for s in [
                                (task_raw.get("model_name") if isinstance(task_raw, dict) else None),
                                (task_raw.get("feature_name") if isinstance(task_raw, dict) else None),
                                (task_raw.get("title") if isinstance(task_raw, dict) else None),
                                (task_raw.get("description") if isinstance(task_raw, dict) else None),
                            ]
                            if isinstance(s, str) and s.strip()
                        ]
                    )
                ).strip()
            ),
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

        # If Beacon didn't provide core identifiers, degrade gracefully (still return a result)
        # while making it obvious in the summary/evidence.
        if not regulation_id or not model_id:
            missing: list[str] = []
            if not regulation_id:
                missing.append("regulation_id")
            if not model_id:
                missing.append("model_id")
            payload["evidence"] = {
                **(payload.get("evidence") or {}),
                "watchtower_missing_fields": missing,
                "watchtower_task_id": str(task_id),
            }
            payload["summary"] = (
                f"{payload.get('summary')}\n\n"
                f"Note: Beacon task did not include {', '.join(missing)}; executor ran with limited context."
            )

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

