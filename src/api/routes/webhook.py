"""
BarberOS - Webhook Route (Legacy)
==================================
Mantido para compatibilidade, mas o recomendado é usar o /chat.
"""
from fastapi import APIRouter
from src.agent.full_engine import create_full_brain

router = APIRouter()
brain = create_full_brain()

@router.post("/webhook/message")
async def legacy_webhook(data: dict):
    # Redireciona logicamente ou avisa que é legado
    return {"message": "Use o endpoint /api/v1/chat para o motor lógico robusto."}
