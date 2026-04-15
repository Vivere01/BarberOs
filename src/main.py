"""
BarberOS - Main Application
==============================
FastAPI server que recebe webhooks do N8N,
processa com o agente LangGraph, e retorna respostas
para enviar via WhatsApp.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.webhook import router as webhook_router
from src.api.routes.chat import router as chat_router
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
    title="BarberOS - Motor Lógico IA",
    description=(
        "Motor lógico de IA que substitui o nó OpenAI nativo do N8N. "
        "POST /api/v1/chat recebe mensagem + contexto e retorna resposta validada. "
        "Anti-alucinação via LangGraph (5 camadas) + LangSmith (observabilidade)."
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

# Middleware de Log Global para diagnóstico
@app.middleware("http")
async def log_requests(request: Request, call_next):
    from src.config.logging_config import get_logger
    import time
    logger = get_logger("http")
    start_time = time.time()
    
    logger.info(f"DEBUG_CONEXAO: Recebendo {request.method} em {request.url.path}")
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    logger.info(f"DEBUG_CONEXAO: Finalizado {request.method} {request.url.path} - Status: {response.status_code} - Tempo: {process_time:.2f}s")
    return response

# Registra rotas
app.include_router(health_router)
app.include_router(chat_router, prefix="/api/v1")  # ★ Endpoint principal: POST /api/v1/chat
app.include_router(webhook_router, prefix="/api/v1")  # Webhook legado (opcional)


@app.get("/")
async def root():
    return {
        "service": "BarberOS",
        "type": "Motor Lógico IA — substitui nó OpenAI do N8N",
        "endpoint_principal": "POST /api/v1/chat",
        "version": "1.0.0",
        "docs": "/docs",
        "como_usar": "No N8N, substitua o nó OpenAI por um HTTP Request apontando para /api/v1/chat",
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
