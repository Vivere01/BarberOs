"""
BarberOS API - ChatBarber PRO Route
===================================
Endpoint exclusivo para o sistema ChatBarber PRO.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Any
from src.agent.chatbarber_pro_engine import create_pro_brain, set_pro_context
from langchain_core.messages import HumanMessage
from src.config.logging_config import get_logger

logger = get_logger("api.chat_pro")

router = APIRouter()
brain_pro = create_pro_brain()

class ChatProInput(BaseModel):
    message: str
    phone: str
    owner_id: str
    api_token: str

@router.post("/chat/pro")
async def process_chat_pro(request: ChatProInput):
    logger.info(f"PRO_REQUEST: Phone={request.phone}, Owner={request.owner_id}")
    
    # Define o contexto de segurança para este request específico
    set_pro_context(api_token=request.api_token, owner_id=request.owner_id)
    input_state = {
        "messages": [HumanMessage(content=request.message)],
        "context_data": {
            "owner_id": request.owner_id,
            "telefone_cliente": request.phone,
        }
    }

    try:
        final_state = await brain_pro.ainvoke(input_state, config=config)
        last_message = final_state["messages"][-1]

        return {
            "response": last_message.content,
            "status": "success"
        }
    except Exception as e:
        logger.error(f"PRO_ENGINE_ERROR: {str(e)}")
        return {
            "response": "Desculpe, tive um problema ao processar sua solicitação no sistema PRO.",
            "status": "error"
        }
