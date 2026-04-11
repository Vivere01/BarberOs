"""
BarberOS - Webhook Routes
===========================
Endpoints que recebem webhooks do N8N e da UzAPI.
Ponto de entrada das mensagens do WhatsApp.
"""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel, Field

from src.agent.graph import create_agent_graph
from src.agent.state import create_initial_state
from src.config.logging_config import get_logger
from src.config.settings import get_settings
from src.observability.tracer import trace_conversation

logger = get_logger("api.webhook")

router = APIRouter(prefix="/webhook", tags=["webhook"])


# ============================================
# Request/Response Schemas
# ============================================

class WhatsAppMessage(BaseModel):
    """Mensagem recebida do WhatsApp via N8N/UzAPI."""
    phone: str = Field(..., description="Telefone do cliente")
    message: str = Field(..., description="Mensagem do cliente")
    name: Optional[str] = Field(None, description="Nome do contato")
    message_id: Optional[str] = Field(None, description="ID da mensagem")
    instance_id: Optional[str] = Field(None, description="ID da instância UzAPI")
    # Contexto da barbearia
    barbershop_id: str = Field(..., description="ID da barbearia")
    system_type: str = Field(..., description="cashbarber ou appbarber")
    # Credenciais do sistema (para scraping)
    system_username: Optional[str] = Field(None, description="Login do sistema")
    system_password: Optional[str] = Field(None, description="Senha do sistema")


class AgentResponse(BaseModel):
    """Resposta do agente para o N8N enviar via WhatsApp."""
    success: bool
    response: str = Field(..., description="Resposta do agente")
    response_type: str = Field(default="text", description="text, buttons, list")
    conversation_id: str
    intent: str
    confidence: float
    needs_human: bool = Field(default=False)
    # Debugging info
    debug: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str = "healthy"
    timestamp: str
    version: str = "1.0.0"


# ============================================
# Armazenamento de conversas em memória
# (Em produção, usar Redis)
# ============================================
_conversation_states: dict[str, dict] = {}


# ============================================
# Endpoints
# ============================================

@router.post("/message", response_model=AgentResponse)
async def receive_message(
    payload: WhatsAppMessage,
    x_webhook_secret: Optional[str] = Header(None),
) -> AgentResponse:
    """
    Recebe mensagem do WhatsApp via N8N webhook.

    Fluxo:
    1. Valida webhook secret
    2. Recupera ou cria estado da conversa
    3. Executa o grafo do agente
    4. Retorna resposta para N8N enviar via WhatsApp
    """
    settings = get_settings()

    # Valida webhook secret
    if settings.n8n_webhook_secret:
        if x_webhook_secret != settings.n8n_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # ID da conversa = barbershop + phone
    conversation_id = f"{payload.barbershop_id}_{payload.phone}"

    logger.info(
        "Message received",
        conversation_id=conversation_id,
        phone=payload.phone[:8] + "****",
        message_preview=payload.message[:50],
        system=payload.system_type,
    )

    try:
        # Recupera ou cria estado
        if conversation_id in _conversation_states:
            state = _conversation_states[conversation_id]
        else:
            state = create_initial_state(
                conversation_id=conversation_id,
                barbershop_id=payload.barbershop_id,
                system_type=payload.system_type,
                client_phone=payload.phone,
            )
            # Atualiza metadata com info do payload
            state["metadata"] = {
                **state["metadata"],
                "barbershop_name": payload.barbershop_id,
                "system_username": payload.system_username,
                "system_password": payload.system_password,
            }

        # Adiciona mensagem do usuário como HumanMessage
        from langchain_core.messages import HumanMessage
        state["messages"] = list(state.get("messages", []))
        state["messages"].append(HumanMessage(content=payload.message))

        # Atualiza info do cliente
        if payload.name:
            client_info = dict(state.get("client_info", {}))
            client_info["name"] = payload.name
            state["client_info"] = client_info

        # Executa o grafo
        graph = create_agent_graph()

        with trace_conversation(conversation_id, payload.barbershop_id):
            result = await graph.ainvoke(state)

        # Salva estado atualizado
        _conversation_states[conversation_id] = result

        # Monta resposta
        guardrail = result.get("guardrail_result", {})
        agent_response = AgentResponse(
            success=True,
            response=result.get("agent_response", ""),
            response_type=result.get("response_type", "text"),
            conversation_id=conversation_id,
            intent=result.get("current_intent", "unknown"),
            confidence=result.get("intent_confidence", 0.0),
            needs_human=result.get("metadata", {}).get("needs_human", False),
            debug={
                "turn_count": result.get("turn_count", 0),
                "conversation_stage": result.get("conversation_stage", ""),
                "guardrail_valid": guardrail.get("is_valid", True),
                "guardrail_confidence": guardrail.get("confidence", 1.0),
                "hallucination_detected": guardrail.get("hallucination_detected", False),
                "violations": guardrail.get("violations", []),
                "errors": result.get("errors", []),
            },
        )

        logger.info(
            "Response generated",
            conversation_id=conversation_id,
            intent=agent_response.intent,
            confidence=agent_response.confidence,
            needs_human=agent_response.needs_human,
            hallucination=guardrail.get("hallucination_detected", False),
        )

        return agent_response

    except Exception as e:
        logger.error(
            "Agent execution failed",
            conversation_id=conversation_id,
            error=str(e),
            error_type=type(e).__name__,
        )

        return AgentResponse(
            success=False,
            response=(
                "Desculpe, tive um probleminha técnico. 😅\n"
                "Vou transferir para um atendente. Um momento!"
            ),
            conversation_id=conversation_id,
            intent="error",
            confidence=0.0,
            needs_human=True,
            debug={
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )


@router.post("/reset/{conversation_id}")
async def reset_conversation(conversation_id: str) -> dict:
    """Reset de uma conversa (debug/admin)."""
    if conversation_id in _conversation_states:
        del _conversation_states[conversation_id]
        logger.info("Conversation reset", conversation_id=conversation_id)
        return {"success": True, "message": "Conversation reset"}

    return {"success": False, "message": "Conversation not found"}


@router.get("/conversations")
async def list_conversations() -> dict:
    """Lista conversas ativas (debug/admin)."""
    conversations = []
    for conv_id, state in _conversation_states.items():
        conversations.append({
            "conversation_id": conv_id,
            "turn_count": state.get("turn_count", 0),
            "stage": state.get("conversation_stage", ""),
            "intent": state.get("current_intent", ""),
            "created_at": state.get("metadata", {}).get("created_at", ""),
        })
    return {"count": len(conversations), "conversations": conversations}
