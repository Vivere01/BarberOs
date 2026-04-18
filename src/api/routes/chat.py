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
    pro_api_key: Optional[str] = None
    instance_name: Optional[str] = None
    evolution_apikey: Optional[str] = None
    metadata: Optional[dict] = None


@router.post("/chat")
async def process_chat(request: ChatInput):
    # Log dos dados para conferência
    logger.info(f"REQUEST_RECEBIDO: WhatsApp {request.phone} | Instance: {request.instance_name}")
    
    config = {"configurable": {"thread_id": request.phone}}

    # Injeta contexto Evolution e PRO
    set_session_context(
        pro_api_key=request.pro_api_key,
        instance_name=request.instance_name,
        evolution_apikey=request.evolution_apikey,
        phone=request.phone,
        metadata=request.metadata
    )

    input_state = {
        "messages": [HumanMessage(content=request.message)],
        "conversation_id": request.phone,
        "barbershop_id": request.instance_name or "default",
        "system_type": "pro",
        "client_info": {"phone": request.phone},
        "current_intent": "unknown",
        "intent_confidence": 0.0,
        "previous_intents": [],
        "conversation_stage": "initial",
        "turn_count": 0,
        "appointment_request": {},
        "scheduling_data": {},
        "agent_response": "",
        "response_type": "text",
        "guardrail_result": {},
        "errors": [],
        "last_error": {},
        "retrieved_knowledge": [],
        "metadata": {"persona": request.persona}
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
