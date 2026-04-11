"""
BarberOS - Main Application
==============================
FastAPI server que recebe webhooks do N8N,
processa com o agente LangGraph, e retorna respostas
para enviar via WhatsApp.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.webhook import router as webhook_router
from src.api.routes.health import router as health_router
from src.config.logging_config import setup_logging, get_logger
from src.config.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown events."""
    settings = get_settings()

    # Setup logging
    setup_logging(
        log_level="DEBUG" if settings.app_debug else "INFO",
        json_output=settings.is_production,
    )

    logger = get_logger("main")
    logger.info(
        "BarberOS starting",
        env=settings.app_env,
        model=settings.openai_model,
        temperature=settings.openai_temperature,
    )

    # Setup Sentry (se configurado)
    if settings.sentry_dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                traces_sample_rate=0.1,
                environment=settings.app_env,
            )
            logger.info("Sentry initialized")
        except ImportError:
            logger.warning("sentry-sdk not installed")

    yield

    logger.info("BarberOS shutting down")


# ============================================
# Cria a aplicação FastAPI
# ============================================

app = FastAPI(
    title="BarberOS - AI Receptionist",
    description=(
        "Infraestrutura de IA para recepcionista virtual de barbearias no WhatsApp. "
        "Integra com CashBarber e AppBarber via web scraping. "
        "Anti-alucinação via LangGraph + validação de respostas."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registra rotas
app.include_router(health_router)
app.include_router(webhook_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "service": "BarberOS",
        "description": "AI Receptionist for Barbershops",
        "version": "1.0.0",
        "docs": "/docs",
    }


# ============================================
# Entry point
# ============================================

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
        log_level="debug" if settings.app_debug else "info",
    )
