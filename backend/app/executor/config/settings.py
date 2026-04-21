from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutorSettings(BaseSettings):
    """
    Executor service configuration.

    This service is intentionally stateless; it fetches all task/regulation/model data
    from Watchtower and returns results back to Watchtower.

    The URL must be reachable from the host running uvicorn. A remote API (e.g. Codespaces)
    cannot use 127.0.0.1 to reach Watchtower on a developer laptop; use the same network
    environment or a tunnel (ngrok/cloudflared) to a public HTTPS URL.
    """

    model_config = SettingsConfigDict(env_prefix="EXECUTOR_", extra="ignore")

    # Prefer 127.0.0.1: some environments resolve "localhost" to ::1 while the
    # peer only listens on IPv4, which produces httpx "All connection attempts failed".
    watchtower_base_url: str = "http://127.0.0.1:8000/api/execution"
    http_timeout_s: float = 20.0
    result_post_retry_attempts: int = 2  # initial try + 1 retry


executor_settings = ExecutorSettings()

