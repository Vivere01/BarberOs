"""
BarberOS - Greeting Node
==========================
Responde saudações com templates determinísticos.
Zero alucinação — usa apenas templates pré-definidos.
"""
from langchain_core.messages import AIMessage

from src.agent.state import AgentState
from src.agent.prompts import RESPONSE_TEMPLATES
from src.config.logging_config import get_logger

logger = get_logger("agent.greeting")


async def handle_greeting(state: AgentState) -> dict:
    """Responde saudações com template fixo — sem LLM, sem alucinação."""
    client_info = state.get("client_info", {})
    client_name = client_info.get("name", "")

    # Usa template determinístico
    name_greeting = f", {client_name}" if client_name else ""
    barbershop_name = state.get("metadata", {}).get("barbershop_name", "nossa barbearia")

    response = RESPONSE_TEMPLATES["greeting"].format(
        client_name_greeting=name_greeting,
        barbershop_name=barbershop_name,
    )

    logger.info(
        "Greeting sent",
        conversation_id=state["conversation_id"],
        client_name=client_name,
    )

    return {
        "agent_response": response,
        "response_type": "text",
        "messages": [AIMessage(content=response)],
    }
