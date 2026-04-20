from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# `__file__` is backend/app/core/config.py → parents[2] is `backend/`, parents[3] is repo root.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(_BACKEND_DIR / ".env"),
            str(_REPO_ROOT / ".env"),
        ),
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

    # Use an absolute default path so the DB doesn't depend on process CWD (common in Codespaces).
    _default_sqlite_path: Path = Path(__file__).resolve().parents[2] / "oel.db"  # backend/oel.db
    database_url: str = f"sqlite+aiosqlite:///{_default_sqlite_path.as_posix()}"

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
    rag_embedding_dim: int = 384

    # Marketplace guardrails (v1)
    marketplace_remote_allowlist: list[str] = []  # e.g. ["https://agents.myco.com/"]
    marketplace_remote_timeout_s: float = 20.0
    marketplace_max_cost_usd: float = 2.00

    # Orchestrator hardening (Phase 2)
    agent_timeout_s_default: float = 30.0
    agent_retry_attempts: int = 3
    agent_retry_backoff_initial_s: float = 0.5
    agent_retry_backoff_max_s: float = 6.0

    # Auth (Phase 5)
    jwt_secret: str = "dev-insecure-secret"
    jwt_issuer: str = "oel"
    jwt_exp_minutes: int = 60 * 24


settings = Settings()

