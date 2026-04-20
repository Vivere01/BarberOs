"""
BarberOS - Settings
===================
Configurações centralizadas via Pydantic Settings.
Todos os campos são lidos do .env automaticamente.
"""
from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── App ──────────────────────────────────────
    app_debug: bool = Field(default=True)
    app_port: int = Field(default=8000)
    app_host: str = Field(default="0.0.0.0")
    app_env: str = Field(default="production")
    is_production: bool = Field(default=True)
    log_level: str = Field(default="INFO")

    # ── OpenAI ───────────────────────────────────
    openai_api_key: str = Field(default="")
    OPENAI_API_KEY: str = Field(default="")        # alias mantido para compat
    openai_model: str = Field(default="gpt-4o-mini")
    openai_temperature: float = Field(default=0.1)

    # ── Sentry (opcional) ────────────────────────
    sentry_dsn: str = Field(default="")

    # ── ChatBarber PRO ───────────────────────────
    chatbarber_base_url: str = Field(default="https://www.chatbarber.pro")
    chatbarber_api_key: str = Field(default="")
    chatbarber_owner_id: str = Field(default="")
    chatbarber_owner_slug: str = Field(default="administrador-chatbarber")

    # ── Evolution / WhatsApp ─────────────────────
    evolution_api_key: str = Field(default="")
    evolution_base_url: str = Field(default="")
    evolution_instance_name: str = Field(default="")

    # ── UZAPI (legado) ───────────────────────────
    uzapi_token: str = Field(default="")
    uzapi_base_url: str = Field(default="")

    # ── ChromaDB / Knowledge ─────────────────────
    chroma_persist_dir: str = Field(default="./data/chroma")

    # ── Aliases legado (cashbarber → chatbarber) ─
    # Código antigo no servidor referencia "cashbarber_*" ao invés de "chatbarber_*"
    # Estes campos garantem compatibilidade até o código do servidor ser atualizado
    cashbarber_base_url: str = Field(default="https://www.chatbarber.pro")
    cashbarber_api_key: str = Field(default="")
    cashbarber_owner_id: str = Field(default="")


@lru_cache(maxsize=1)
def get_settings():
    return Settings()

