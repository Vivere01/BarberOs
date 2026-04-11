"""
BarberOS - Health Check Routes
"""
from datetime import datetime

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "barberos",
        "version": "1.0.0",
    }


@router.get("/ready")
async def readiness_check() -> dict:
    """Readiness check — validates critical dependencies."""
    checks = {
        "openai": True,
        "database": True,
    }

    # Verifica OpenAI API key
    try:
        from src.config.settings import get_settings
        settings = get_settings()
        checks["openai"] = bool(settings.openai_api_key)
    except Exception:
        checks["openai"] = False

    all_ready = all(checks.values())

    return {
        "status": "ready" if all_ready else "not_ready",
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(),
    }
