"""
BarberOS - Cancellation Node
===============================
Gerencia cancelamento e remarcação de agendamentos.
"""
from langchain_core.messages import AIMessage

from src.agent.state import AgentState, ConversationStage
from src.agent.prompts import RESPONSE_TEMPLATES
from src.config.logging_config import get_logger

logger = get_logger("agent.cancellation")


async def handle_cancellation(state: AgentState) -> dict:
    """
    Gerencia cancelamento de agendamento.
    SEMPRE confirma antes de cancelar.
    """
    stage = state.get("conversation_stage", "")

    if stage == ConversationStage.CONFIRMING.value:
        last_msg = _get_last_user_message(state)
        if last_msg in {"sim", "s", "confirmo", "ok", "pode", "yes"}:
            # Executa cancelamento via scraper
            response = RESPONSE_TEMPLATES["appointment_cancelled"]
            logger.info(
                "Appointment cancelled",
                conversation_id=state["conversation_id"],
            )
            return {
                "agent_response": response,
                "response_type": "text",
                "messages": [AIMessage(content=response)],
                "conversation_stage": ConversationStage.COMPLETED.value,
            }
        else:
            response = "Ok! Seu agendamento continua mantido. 😊"
            return {
                "agent_response": response,
                "response_type": "text",
                "messages": [AIMessage(content=response)],
                "conversation_stage": ConversationStage.COMPLETED.value,
            }

    # Pede confirmação antes de cancelar
    response = (
        "Você deseja cancelar seu agendamento?\n\n"
        "⚠️ Esta ação não pode ser desfeita.\n"
        "Confirma o cancelamento? (Sim/Não)"
    )

    return {
        "agent_response": response,
        "response_type": "buttons",
        "messages": [AIMessage(content=response)],
        "conversation_stage": ConversationStage.CONFIRMING.value,
    }


def _get_last_user_message(state: AgentState) -> str:
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "type") and msg.type == "human":
            return msg.content.lower().strip()
    return ""
