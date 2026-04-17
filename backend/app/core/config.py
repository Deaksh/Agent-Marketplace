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

    # --- LLM providers (optional) ---
    # System remains functional without any LLM key configured.

    # OpenAI-compatible (kept for future)
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4.1-mini"

    # Groq (OpenAI-compatible API)
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.1-8b-instant"

    # Hugging Face (for embedding rerank in retrieval)
    hf_token: str | None = None
    hf_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Marketplace guardrails (v1)
    marketplace_remote_allowlist: list[str] = []  # e.g. ["https://agents.myco.com/"]
    marketplace_remote_timeout_s: float = 20.0
    marketplace_max_cost_usd: float = 2.00


settings = Settings()

