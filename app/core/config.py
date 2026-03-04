"""Application configuration using pydantic-settings."""

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "Self-Correcting Data Validation Agent"
    debug: bool = False

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data_validation.db"

    # ── LLM ──────────────────────────────────────────────────────────────
    llm_provider: LLMProvider = LLMProvider.GEMINI

    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4"
    openai_fallback_model: str = "gpt-3.5-turbo"  # cheaper model for retries

    # Google Gemini  (default — diagram specifies Gemini Flash)
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_fallback_model: str = "gemini-2.0-flash"  # same model (already fast)

    # Common LLM settings
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    llm_concurrency: int = 10  # safer default to avoid local OOM / process kills
    use_fallback_for_retries: bool = True  # use cheaper model for correction retries

    # ── Retry / correction ───────────────────────────────────────────────
    max_retries: int = 3
    retry_budget_per_hour: int = 1000
    per_key_retry_budget_per_hour: int = 100  # per API-key budget (tenant isolation)

    # ── Degradation detection ────────────────────────────────────────────
    degradation_window_seconds: int = 300  # 5-minute window for spike detection
    degradation_retry_rate_threshold: float = 0.5  # if >50% of jobs retry, trigger fallback
    auto_fallback_on_degradation: bool = True  # automatically use fallback model when degraded

    # ── Redis (job queue) ────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    use_redis_queue: bool = True  # set True to use Redis worker instead of BackgroundTasks

    # ── Logging ──────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── API Security ─────────────────────────────────────────────────────
    # Comma-separated list of valid API keys (empty = auth disabled)
    api_keys_str: str = ""  # stored as comma-separated string
    rate_limit_rpm: int = 60  # requests per minute per API key

    # ── Job Timeouts ─────────────────────────────────────────────────────
    job_timeout_seconds: int = 300  # max time for a job before marked as timed out

    @property
    def api_keys(self) -> list[str]:
        """Parse comma-separated API_KEYS_STR into a list."""
        if not self.api_keys_str.strip():
            return []
        return [k.strip() for k in self.api_keys_str.split(",") if k.strip()]


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton for application settings."""
    return Settings()
