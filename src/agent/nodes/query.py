"""
BarberOS - Query Node
=======================
Responde perguntas sobre serviços, preços, horários e localização.
Usa APENAS dados do sistema ou da knowledge base — nunca inventa.
"""
from langchain_core.messages import AIMessage

from src.agent.state import AgentState, IntentType
from src.agent.prompts import RESPONSE_TEMPLATES
from src.config.logging_config import get_logger

logger = get_logger("agent.query")


async def handle_query(state: AgentState) -> dict:
    """
    Responde consultas informacionais usando dados reais.

    Se os dados não estão disponíveis, encaminha para humano
    ao invés de inventar uma resposta.
    """
    intent = state.get("current_intent", IntentType.UNKNOWN.value)
    scheduling_data = state.get("scheduling_data", {})
    retrieved_knowledge = state.get("retrieved_knowledge", [])
    metadata = state.get("metadata", {})

    response = ""

    if intent == IntentType.QUERY_SERVICES.value:
        services = scheduling_data.get("services", [])
        if services:
            formatted = "\n".join(
                f"• {s.get('name', '')} — R$ {s.get('price', 'consultar')}"
                for s in services
            )
            response = RESPONSE_TEMPLATES["services_list"].format(
                services_formatted=formatted,
            )
        else:
            response = _try_knowledge_base(retrieved_knowledge, "serviços")

    elif intent == IntentType.QUERY_PRICES.value:
        services = scheduling_data.get("services", [])
        if services and any(s.get("price") for s in services):
            formatted = "\n".join(
                f"• {s.get('name', '')}: R$ {s.get('price', 'consultar')}"
                for s in services
            )
            response = RESPONSE_TEMPLATES["prices_list"].format(
                prices_formatted=formatted,
            )
        else:
            response = _try_knowledge_base(retrieved_knowledge, "preços")

    elif intent == IntentType.QUERY_HOURS.value:
        hours = scheduling_data.get("business_hours", {})
        if hours:
            formatted = _format_business_hours(hours)
            response = RESPONSE_TEMPLATES["business_hours"].format(
                hours_formatted=formatted,
            )
        else:
            response = _try_knowledge_base(retrieved_knowledge, "horário")

    elif intent == IntentType.QUERY_LOCATION.value:
        location = metadata.get("address", "")
        if location:
            response = f"📍 Nosso endereço:\n{location}"
            maps_link = metadata.get("maps_link", "")
            if maps_link:
                response += f"\n\n🗺️ Google Maps: {maps_link}"
        else:
            response = _try_knowledge_base(retrieved_knowledge, "localização")

    elif intent == IntentType.FAQ.value:
        if retrieved_knowledge:
            # Usa conhecimento do RAG
            response = retrieved_knowledge[0]  # Resposta mais relevante
        else:
            response = RESPONSE_TEMPLATES["data_not_found"]

    elif intent == IntentType.CHECK_APPOINTMENT.value:
        response = (
            "Deixa eu verificar seus agendamentos... 🔍\n"
            "Pode me informar seu nome completo para que eu possa buscar?"
        )

    # Fallback se nenhuma resposta foi gerada
    if not response:
        response = RESPONSE_TEMPLATES["data_not_found"]
        logger.warning(
            "No data available for query",
            intent=intent,
            conversation_id=state["conversation_id"],
        )

    logger.info(
        "Query handled",
        intent=intent,
        has_data=bool(response != RESPONSE_TEMPLATES["data_not_found"]),
        conversation_id=state["conversation_id"],
    )

    return {
        "agent_response": response,
        "response_type": "text",
        "messages": [AIMessage(content=response)],
    }


def _try_knowledge_base(knowledge: list[str], topic: str) -> str:
    """Tenta usar a knowledge base, senão retorna fallback."""
    if knowledge:
        return knowledge[0]
    return RESPONSE_TEMPLATES["data_not_found"]


def _format_business_hours(hours: dict) -> str:
    """Formata horário de funcionamento para exibição."""
    days_pt = {
        "monday": "Segunda",
        "tuesday": "Terça",
        "wednesday": "Quarta",
        "thursday": "Quinta",
        "friday": "Sexta",
        "saturday": "Sábado",
        "sunday": "Domingo",
    }

    lines = []
    for day_en, day_pt_name in days_pt.items():
        info = hours.get(day_en, {})
        if info.get("closed"):
            lines.append(f"• {day_pt_name}: Fechado")
        elif info.get("open") and info.get("close"):
            lines.append(f"• {day_pt_name}: {info['open']} - {info['close']}")

    return "\n".join(lines) if lines else "Horário não disponível no momento."
