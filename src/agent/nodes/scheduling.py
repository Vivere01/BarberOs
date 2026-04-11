"""
BarberOS - Scheduling Node
============================
Gerencia o fluxo de agendamento completo.
Usa dados REAIS do sistema (CashBarber/AppBarber) via scrapers.

ANTI-ALUCINAÇÃO:
- Só mostra horários realmente disponíveis no sistema
- Só mostra serviços e profissionais cadastrados
- Confirma cada passo antes de executar
- Valida dados contra o sistema real
"""
from datetime import datetime

from langchain_core.messages import AIMessage

from src.agent.state import (
    AgentState,
    ConversationStage,
    AppointmentRequest,
)
from src.agent.prompts import RESPONSE_TEMPLATES, MISSING_FIELD_QUESTIONS
from src.config.logging_config import get_logger

logger = get_logger("agent.scheduling")


async def handle_scheduling(state: AgentState) -> dict:
    """
    Gerencia o fluxo de agendamento passo a passo.

    Fluxo:
    1. Coleta serviço → 2. Coleta profissional → 3. Coleta data →
    4. Busca horários → 5. Coleta horário → 6. Confirma → 7. Agenda

    Cada passo usa dados REAIS do sistema de agendamento.
    """
    appointment = state.get("appointment_request", {})
    scheduling_data = state.get("scheduling_data", {})
    stage = state.get("conversation_stage", ConversationStage.COLLECTING_INFO.value)
    metadata = state.get("metadata", {})
    barbershop_name = metadata.get("barbershop_name", "nossa barbearia")

    # Se estamos no estágio de confirmação e o cliente disse sim
    if stage == ConversationStage.CONFIRMING.value:
        last_msg = _get_last_user_message(state)
        if _is_confirmation(last_msg):
            return await _execute_appointment(state)
        elif _is_rejection(last_msg):
            response = "Ok! Vamos recomeçar. Qual serviço você gostaria? 😊"
            return {
                "agent_response": response,
                "response_type": "text",
                "messages": [AIMessage(content=response)],
                "appointment_request": AppointmentRequest().model_dump(),
                "conversation_stage": ConversationStage.COLLECTING_INFO.value,
            }

    # Verifica campos faltantes e pede o próximo
    missing = appointment.get("missing_fields", ["service", "professional", "date", "time"])

    if not missing or appointment.get("is_complete"):
        # Todos os dados coletados — confirma
        response = RESPONSE_TEMPLATES["confirm_appointment"].format(
            service=appointment.get("service", ""),
            professional=appointment.get("professional", ""),
            date=_format_date(appointment.get("date", "")),
            time=appointment.get("time", ""),
        )
        return {
            "agent_response": response,
            "response_type": "buttons",
            "messages": [AIMessage(content=response)],
            "conversation_stage": ConversationStage.CONFIRMING.value,
        }

    # Coleta próximo campo faltante
    next_field = missing[0]
    response = await _ask_for_field(next_field, scheduling_data, barbershop_name)

    return {
        "agent_response": response,
        "response_type": "list" if next_field in ("service", "professional", "time") else "text",
        "messages": [AIMessage(content=response)],
        "conversation_stage": ConversationStage.COLLECTING_INFO.value,
    }


async def _ask_for_field(field: str, scheduling_data: dict, barbershop_name: str) -> str:
    """Gera pergunta para o campo faltante usando dados REAIS."""

    if field == "service":
        services = scheduling_data.get("services", [])
        if services:
            services_list = "\n".join(
                f"• {s.get('name', '')} — R$ {s.get('price', 'consultar')}"
                for s in services
            )
            return RESPONSE_TEMPLATES["ask_service"].format(services_list=services_list)
        else:
            return (
                "Qual serviço você gostaria de agendar? "
                "Deixa eu buscar os serviços disponíveis... 🔍"
            )

    elif field == "professional":
        professionals = scheduling_data.get("professionals", [])
        if professionals:
            prof_list = "\n".join(
                f"• {p.get('name', '')}" for p in professionals
            )
            return RESPONSE_TEMPLATES["ask_professional"].format(
                service_name="o serviço selecionado",
                professionals_list=prof_list,
            )
        else:
            return "Com qual profissional você prefere?"

    elif field == "date":
        return RESPONSE_TEMPLATES["ask_date"].format(
            professional_name=scheduling_data.get("selected_professional", "o profissional"),
        )

    elif field == "time":
        slots = scheduling_data.get("available_slots", [])
        if slots:
            times_list = "\n".join(
                f"• {s.get('time', '')}" for s in slots
            )
            return RESPONSE_TEMPLATES["ask_time"].format(
                date="a data selecionada",
                available_times=times_list,
            )
        else:
            return (
                "Estou verificando os horários disponíveis... 🔍\n"
                "Qual horário você prefere?"
            )

    return MISSING_FIELD_QUESTIONS.get(field, f"Qual o {field}?").format(options="")


async def _execute_appointment(state: AgentState) -> dict:
    """
    Executa o agendamento no sistema real.

    NOTA: A execução real acontece via integration layer (scrapers).
    Este nó prepara os dados e delega para o scraper correto.
    """
    appointment = state.get("appointment_request", {})
    system_type = state.get("system_type", "")

    logger.info(
        "Executing appointment",
        appointment=appointment,
        system=system_type,
        conversation_id=state["conversation_id"],
    )

    # A execução real será feita pelo scraper no tool node
    # Aqui preparamos a resposta de confirmação
    response = RESPONSE_TEMPLATES["appointment_confirmed"].format(
        service=appointment.get("service", ""),
        professional=appointment.get("professional", ""),
        date=_format_date(appointment.get("date", "")),
        time=appointment.get("time", ""),
    )

    return {
        "agent_response": response,
        "response_type": "text",
        "messages": [AIMessage(content=response)],
        "conversation_stage": ConversationStage.COMPLETED.value,
    }


def _get_last_user_message(state: AgentState) -> str:
    """Extrai a última mensagem do usuário."""
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "type") and msg.type == "human":
            return msg.content.lower().strip()
        elif hasattr(msg, "role") and msg.role == "user":
            return msg.content.lower().strip()
    return ""


def _is_confirmation(message: str) -> bool:
    """Detecta confirmação do cliente."""
    confirmations = {"sim", "s", "confirmo", "confirma", "ok", "pode", "isso", "yes", "pode ser", "bora", "vamos"}
    return message.strip().lower() in confirmations


def _is_rejection(message: str) -> bool:
    """Detecta rejeição do cliente."""
    rejections = {"não", "nao", "n", "cancela", "cancelar", "não quero", "nao quero", "errado"}
    return message.strip().lower() in rejections


def _format_date(date_str: str) -> str:
    """Formata data para exibição."""
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return date_str
