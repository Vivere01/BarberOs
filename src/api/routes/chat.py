"""
BarberOS API - Brain Node
==========================
Devolve Resposta + Intenções Estruturadas
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Any
from src.agent.full_engine import create_full_brain, set_session_context
from langchain_core.messages import HumanMessage
from src.config.logging_config import get_logger
from src.config.settings import get_settings

logger = get_logger("api.chat")

router = APIRouter()
brain = create_full_brain()


class ChatInput(BaseModel):
    message: str
    phone: str
    persona: Optional[str] = None
    barbershop_context: Optional[Any] = None
    inbox_do_cliente: Optional[str] = None
    contact_id: Optional[str] = None
    conversation_id: Optional[str] = None


@router.post("/chat")
async def process_chat(request: ChatInput):
    # Log para diagnóstico de entrada
    logger.info("="*50)
    logger.info(f">>> NOVA MENSAGEM RECEBIDA: {request.phone} -> {request.message[:50]}...")
    logger.info("="*50)
    
    config = {"configurable": {"thread_id": request.phone}}

    # ★ Injeta contexto Chatwoot nas tools ANTES de invocar o brain
    set_session_context(
        inbox=request.inbox_do_cliente,
        contact_id=request.contact_id,
        conversation_id=request.conversation_id,
        system_info=request.barbershop_context
    )

    input_state = {
        "messages": [HumanMessage(content=request.message)],
        "context_data": {
            "persona": request.persona,
            "system_info": request.barbershop_context,
            "inbox_do_cliente": request.inbox_do_cliente,
            "contact_id": request.contact_id,
            "conversation_id": request.conversation_id,
            "telefone_cliente": request.phone,
        },
        "needs_human": False
    }

    # Limite de recursão padrão do LangGraph é 25. 5 era muito baixo para agentes com ferramentas.
    config["recursion_limit"] = 25

    # Validação rápida de configuração
    settings = get_settings()
    if not settings.openai_api_key or len(settings.openai_api_key) < 10:
        logger.error("OPENAI_API_KEY não configurada corretamente no .env")
        return {
            "response": "Desculpe, o sistema está em manutenção (chave de API ausente).",
            "intent": "error",
            "needs_human": True
        }

    try:
        final_state = await brain.ainvoke(input_state, config=config)

        # Garante que temos mensagens e pega a última
        messages = final_state.get("messages", [])
        if not messages:
            raise ValueError("O agente retornou um estado sem mensagens.")

        last_message = messages[-1]

        return {
            "response": last_message.content,
            "intent": final_state.get("intent", "conversational"),
            "needs_human": final_state.get("needs_human", False)
        }
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()

        # Identifica se é erro de recursão (loop infinito)
        error_msg = str(e)
        if "recursion_limit" in error_msg.lower():
            logger.error(f"LOOP DETECTADO: O agente excedeu o limite de {config['recursion_limit']} passos.")
        else:
            logger.error(f"ERRO CRÍTICO NO AGENTE: {error_msg}", extra={"trace": error_trace})

        print(f"--- TRACEBACK ---\n{error_trace}")

        return {
            "response": "Ok já irei direcionar para alguém da equipe, só um instante",
            "intent": "error",
            "needs_human": True
        }
