"""
HireFlow AI — Application Settings
Loads configuration from the .env file via pydantic-settings.
Never hardcode secrets here — all values come from environment variables.
"""

from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised settings object parsed once at startup.

    All fields map directly to keys in .env / .env.example.
    Optional fields default to None so the app can start without every
    provider configured — the LLM client validates the required keys at
    construction time.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Extra fields in .env are silently ignored so adding new vars
        # to .env doesn't break a running instance.
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # LLM Provider selection
    # ------------------------------------------------------------------ #
    LLM_PROVIDER: str = "groq"

    # Groq (free tier — recommended for students)
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # Google Gemini (free tier)
    GEMINI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # OpenAI (paid)
    OPENAI_API_KEY: Optional[str] = None

    # Anthropic (paid)
    ANTHROPIC_API_KEY: Optional[str] = None

    # Ollama (fully local — no key needed)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/hireflow"

    # ------------------------------------------------------------------ #
    # Web Search
    # ------------------------------------------------------------------ #
    TAVILY_API_KEY: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Email Delivery
    # ------------------------------------------------------------------ #
    SENDGRID_API_KEY: Optional[str] = None
    FROM_EMAIL: str = "hireflow@yourdomain.com"

    # ------------------------------------------------------------------ #
    # File Storage
    # ------------------------------------------------------------------ #
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_PATH: str = "./data"

    # ------------------------------------------------------------------ #
    # Application Config
    # ------------------------------------------------------------------ #
    APP_ENV: str = "development"
    DEBUG: bool = False
    SECRET_KEY: Optional[str] = None
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # ------------------------------------------------------------------ #
    # Frontend
    # ------------------------------------------------------------------ #
    NEXT_PUBLIC_API_URL: str = "http://localhost:8000"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value: object) -> object:
        """Handle deployment-style DEBUG values such as DEBUG=release."""
        if isinstance(value, str) and value.strip().lower() in {"release", "prod"}:
            return False
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton.

    Using @lru_cache means the .env file is read exactly once per process,
    which is both efficient and makes it easy to override in tests by
    clearing the cache: get_settings.cache_clear().
    """
    return Settings()
