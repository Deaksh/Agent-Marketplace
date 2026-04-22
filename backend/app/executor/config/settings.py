from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Match `app.core.config`: load repo-root and backend `.env` so EXECUTOR_* vars work
# without exporting them in the shell before uvicorn.
# `settings.py` is backend/app/executor/config/settings.py → parents[3] is `backend/`, [4] is repo root.
_BACKEND_DIR = Path(__file__).resolve().parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[4]


class ExecutorSettings(BaseSettings):
    """
    Executor service configuration.

    This service is intentionally stateless; it fetches all task/regulation/model data
    from Watchtower and returns results back to Watchtower.

    The URL must be reachable from the host running uvicorn. A remote API (e.g. Codespaces)
    cannot use 127.0.0.1 to reach Watchtower on a developer laptop; use the same network
    environment or a tunnel (ngrok/cloudflared) to a public HTTPS URL.
    """

    model_config = SettingsConfigDict(
        env_prefix="EXECUTOR_",
        env_file=(
            str(_BACKEND_DIR / ".env"),
            str(_REPO_ROOT / ".env"),
        ),
        env_ignore_empty=True,
        extra="ignore",
    )

    # Origin only (no path): paths are /tasks/..., /regulations/..., etc. Beacon exposes
    # /tasks/{task_id} at the root, not under /api/execution.
    watchtower_base_url: str = "http://127.0.0.1:8000"
    http_timeout_s: float = 20.0
    result_post_retry_attempts: int = 2  # initial try + 1 retry
    # Beacon OpenAPI has no POST /tasks/{id}/result; set True until that route exists.
    skip_result_post: bool = False

    # Beacon may require the same admin key as /admin/* (see 401/405 without it).
    watchtower_api_key: str | None = None
    # Beacon's OpenAPI commonly declares this header as "x-api-key"
    watchtower_api_key_header: str = "x-api-key"

    # How to fetch /tasks/{task_id}. Beacon exposes PATCH-only for /tasks/{id}.
    watchtower_task_http_method: Literal["GET", "POST", "PATCH"] = "PATCH"

    # Dev only: run analysis without calling Beacon (no URL, no admin key). Not for production.
    dev_mock_watchtower: bool = False


executor_settings = ExecutorSettings()

