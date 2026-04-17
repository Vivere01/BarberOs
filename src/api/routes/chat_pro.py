"""
BarberOS API - ChatBarber PRO Route
===================================
Endpoint exclusivo para o sistema ChatBarber PRO.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Any
from src.agent.chatbarber_pro_engine import create_pro_brain, set_pro_context, transcribe_audio
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
    audio_base64: Optional[str] = None

@router.post("/chat/pro")
async def process_chat_pro(request: ChatProInput):
    logger.info(f"PRO_REQUEST: Phone={request.phone}, Owner={request.owner_id}")
    
    # Transcrição de áudio se presente
    message_text = request.message
    if request.audio_base64:
        logger.info("PRO_AUDIO: Recebido áudio base64, iniciando transcrição...")
        transcribed = await transcribe_audio(request.audio_base64)
        if transcribed:
            message_text = transcribed
            logger.info(f"PRO_AUDIO_TRANSCRITO: {transcribed[:80]}...")
        else:
            logger.warning("PRO_AUDIO: Transcrição falhou, usando texto original ou aviso")
            if not message_text or message_text.strip() == "":
                message_text = "[O cliente enviou um áudio mas não foi possível transcrever. Peça gentilmente para ele digitar o que deseja.]"

    # Define o contexto de segurança para este request específico
    set_pro_context(api_token=request.api_token, owner_id=request.owner_id)
    
    # FIX BUG #1: config PRECISA ser criado aqui — era NameError antes
    config = {
        "configurable": {"thread_id": request.phone},
        "recursion_limit": 25,
    }
    
    input_state = {
        "messages": [HumanMessage(content=message_text)],
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
        logger.error(f"PRO_ENGINE_ERROR: {str(e)}", exc_info=True)
        return {
            "response": "Poxa, deu uma oscilação aqui no meu sistema. Pode repetir o que deseja? 😊",
            "status": "error"
        }
