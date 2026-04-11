"""
BarberOS - Fallback & Human Handoff Node
==========================================
Nó de fallback quando o agente não consegue resolver.
Garante que o cliente SEMPRE receba uma resposta útil.
"""
from langchain_core.messages import AIMessage

from src.agent.state import AgentState, ConversationStage
from src.agent.prompts import RESPONSE_TEMPLATES
from src.config.logging_config import get_logger

logger = get_logger("agent.fallback")


async def handle_fallback(state: AgentState) -> dict:
    """
    Gerencia situações onde o agente não pode resolver.

    Cenários:
    1. Intenção desconhecida
    2. Confiança muito baixa
    3. Erro no sistema
    4. Cliente pede humano
    5. Reclamação
    """
    intent = state.get("current_intent", "unknown")
    errors = state.get("errors", [])

    if intent == "complaint":
        response = (
            "Lamento que você tenha tido um problema. 😔\n"
            "Vou transferir você para um responsável que poderá "
            "ajudar da melhor forma.\n"
            "Por favor, aguarde um momento. 🙏"
        )
    elif intent == "human_handoff":
        response = RESPONSE_TEMPLATES["human_handoff"]
    elif errors:
        response = RESPONSE_TEMPLATES["error_fallback"]
    else:
        response = RESPONSE_TEMPLATES["data_not_found"]

    logger.info(
        "Fallback triggered",
        intent=intent,
        has_errors=bool(errors),
        conversation_id=state["conversation_id"],
    )

    return {
        "agent_response": response,
        "response_type": "text",
        "messages": [AIMessage(content=response)],
        "conversation_stage": ConversationStage.HANDOFF.value,
        "metadata": {
            **state.get("metadata", {}),
            "needs_human": True,
            "handoff_reason": intent,
        },
    }
