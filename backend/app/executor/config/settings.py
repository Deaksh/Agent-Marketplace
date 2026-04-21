from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutorSettings(BaseSettings):
    """
    Executor service configuration.

    This service is intentionally stateless; it fetches all task/regulation/model data
    from Watchtower and returns results back to Watchtower.
    """

    model_config = SettingsConfigDict(env_prefix="EXECUTOR_", extra="ignore")

    watchtower_base_url: str = "http://localhost:8000/api/execution"
    http_timeout_s: float = 20.0
    result_post_retry_attempts: int = 2  # initial try + 1 retry


executor_settings = ExecutorSettings()

