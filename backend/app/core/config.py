from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str = "Outcome Execution Layer (MVP)"
    environment: str = "dev"
    api_prefix: str = ""

    cors_allow_origins: list[str] = [
        "http://localhost:5273",
        "http://127.0.0.1:5273",
    ]

    database_url: str = "sqlite+aiosqlite:///./oel.db"

    # Optional. System remains functional without OpenAI configured.
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4.1-mini"


settings = Settings()

