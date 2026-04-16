"""
BarberOS - Centralized Settings
================================
All configuration is loaded from environment variables via Pydantic Settings.
This ensures type safety and validation at startup.
"""
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: str = Field(default="development", description="Environment: development, staging, production")
    app_debug: bool = Field(default=False)
    app_port: int = Field(default=8000)
    app_host: str = Field(default="0.0.0.0")
    secret_key: str = Field(default="change-me-in-production")

    # --- OpenAI ---
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")
    openai_temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    openai_max_tokens: int = Field(default=1024, ge=100, le=4096)

    # --- LangSmith ---
    langchain_tracing_v2: bool = Field(default=True)
    langchain_api_key: str = Field(default="")
    langchain_project: str = Field(default="barberos-production")
    langchain_endpoint: str = Field(default="https://api.smith.langchain.com")

    # --- Database ---
    database_url: str = Field(default="sqlite+aiosqlite:///./barberos.db")

    # --- Redis ---
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- UzaAPI (WhatsApp) ---
    uzapi_base_url: str = Field(default="https://api.uzapi.com.br")
    uzapi_token: str = Field(default="")

    # --- CashBarber ---
    cashbarber_base_url: str = Field(default="https://app.sistemacashbarber.com.br")
    cashbarber_login_endpoint: str = Field(default="/api/auth/login")

    # --- AppBarber ---
    appbarber_base_url: str = Field(default="https://admin.appbarber.com.br")
    appbarber_login_endpoint: str = Field(default="/api/auth/login")

    # --- Sentry ---
    sentry_dsn: Optional[str] = Field(default=None)

    # AI API Keys
    GROQ_API_KEY: str = Field(default="")
    OPENAI_API_KEY: str = Field(default="")
    groq_model: str = Field(default="llama-3.3-70b-versatile")

    # --- Evolution API ---
    evolution_api_key: str = Field(default="")
    evolution_base_url: str = Field(default="")
    evolution_instance_name: str = Field(default="")

    # --- ChromaDB ---
    chroma_persist_dir: str = Field(default="./data/chromadb")
    chroma_collection_name: str = Field(default="barbershop_knowledge")

    # --- N8N ---
    n8n_webhook_secret: str = Field(default="")

    # --- Guardrails ---
    max_response_length: int = Field(default=500)
    hallucination_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    enable_pii_filter: bool = Field(default=True)
    enable_human_handoff: bool = Field(default=True)
    human_handoff_confidence_threshold: float = Field(default=0.4, ge=0.0, le=1.0)

    @field_validator("openai_temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """Low temperature = less creative = less hallucination."""
        if v > 0.3:
            import warnings
            warnings.warn(
                f"Temperature {v} is high for a receptionist agent. "
                "Consider using 0.1-0.2 to reduce hallucination risk.",
                UserWarning,
                stacklevel=2,
            )
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings singleton."""
    return Settings()
