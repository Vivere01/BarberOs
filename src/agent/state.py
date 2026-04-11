"""
BarberOS - Agent State Definition
===================================
Define o estado completo do agente LangGraph.
Cada campo é rastreado para debugging e auditoria.

O estado é o "cérebro" do agente — tudo que ele sabe sobre a conversa
atual está aqui. Isso evita alucinação porque o agente só pode
responder com base no que está no estado, não na memória do LLM.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Optional

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ============================================
# Enums para classificação determinística
# ============================================

class IntentType(str, Enum):
    """Intenções possíveis do cliente. Lista FECHADA = sem alucinação."""
    GREETING = "greeting"
    SCHEDULE_APPOINTMENT = "schedule_appointment"
    CANCEL_APPOINTMENT = "cancel_appointment"
    RESCHEDULE_APPOINTMENT = "reschedule_appointment"
    CHECK_AVAILABILITY = "check_availability"
    CHECK_APPOINTMENT = "check_appointment"
    QUERY_SERVICES = "query_services"
    QUERY_PRICES = "query_prices"
    QUERY_HOURS = "query_hours"
    QUERY_LOCATION = "query_location"
    FAQ = "faq"
    COMPLAINT = "complaint"
    HUMAN_HANDOFF = "human_handoff"
    UNKNOWN = "unknown"


class SystemType(str, Enum):
    """Sistemas de agendamento suportados."""
    CASHBARBER = "cashbarber"
    APPBARBER = "appbarber"


class ConversationStage(str, Enum):
    """Estágio da conversa — máquina de estados."""
    INITIAL = "initial"
    COLLECTING_INFO = "collecting_info"
    CONFIRMING = "confirming"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR = "error"
    HANDOFF = "handoff"


class ConfidenceLevel(str, Enum):
    """Nível de confiança da resposta."""
    HIGH = "high"           # > 0.8 — responde direto
    MEDIUM = "medium"       # 0.5 - 0.8 — pede confirmação
    LOW = "low"             # < 0.5 — encaminha para humano


# ============================================
# Modelos de dados estruturados
# ============================================

class ClientInfo(BaseModel):
    """Informações do cliente extraídas da conversa."""
    phone: str = ""
    name: str = ""
    last_visit: Optional[str] = None
    is_registered: Optional[bool] = None
    preferences: dict[str, Any] = Field(default_factory=dict)


class AppointmentRequest(BaseModel):
    """Dados de uma solicitação de agendamento."""
    service: Optional[str] = None
    professional: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    notes: Optional[str] = None
    # Campos de validação
    is_complete: bool = False
    missing_fields: list[str] = Field(default_factory=list)


class SchedulingData(BaseModel):
    """Dados retornados pelo sistema de agendamento."""
    available_slots: list[dict[str, Any]] = Field(default_factory=list)
    services: list[dict[str, Any]] = Field(default_factory=list)
    professionals: list[dict[str, Any]] = Field(default_factory=list)
    business_hours: dict[str, Any] = Field(default_factory=dict)
    # Metadados de scraping
    data_source: Optional[SystemType] = None
    fetched_at: Optional[str] = None
    is_stale: bool = False


class GuardrailResult(BaseModel):
    """Resultado da validação de guardrails."""
    is_valid: bool = True
    violations: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.HIGH
    hallucination_detected: bool = False
    pii_detected: bool = False
    suggested_correction: Optional[str] = None


class ErrorContext(BaseModel):
    """Contexto de erro para debugging rápido."""
    error_id: str = ""
    error_type: str = ""
    error_message: str = ""
    node_name: str = ""
    timestamp: str = ""
    stack_trace: Optional[str] = None
    recovery_action: str = ""
    # Dados para reprodução
    input_snapshot: dict[str, Any] = Field(default_factory=dict)


# ============================================
# Estado Principal do Agente
# ============================================

class AgentState(TypedDict):
    """
    Estado completo do agente LangGraph.

    PRINCÍPIO ANTI-ALUCINAÇÃO:
    O agente NUNCA inventa dados. Tudo que ele pode usar
    para responder está explicitamente neste estado.
    Se um campo está vazio, o agente DEVE pedir a informação
    ao cliente ou buscar no sistema de agendamento.
    """

    # --- Mensagens da conversa (LangGraph gerencia) ---
    messages: Annotated[list, add_messages]

    # --- Identificação ---
    conversation_id: str
    barbershop_id: str
    system_type: str  # "cashbarber" ou "appbarber"

    # --- Cliente ---
    client_info: dict  # Serializado de ClientInfo

    # --- Classificação de intenção ---
    current_intent: str  # IntentType value
    intent_confidence: float
    previous_intents: list[str]

    # --- Estágio da conversa ---
    conversation_stage: str  # ConversationStage value
    turn_count: int

    # --- Dados de agendamento ---
    appointment_request: dict  # Serializado de AppointmentRequest
    scheduling_data: dict  # Serializado de SchedulingData

    # --- Resposta do agente ---
    agent_response: str
    response_type: str  # "text", "buttons", "list"

    # --- Guardrails ---
    guardrail_result: dict  # Serializado de GuardrailResult

    # --- Erros ---
    errors: list[dict]  # Lista de ErrorContext serializados
    last_error: dict  # Último ErrorContext

    # --- Knowledge Base ---
    retrieved_knowledge: list[str]  # Documentos relevantes do RAG

    # --- Metadados ---
    metadata: dict


def create_initial_state(
    conversation_id: str,
    barbershop_id: str,
    system_type: str,
    client_phone: str,
) -> AgentState:
    """Cria estado inicial limpo para uma nova conversa."""
    return AgentState(
        messages=[],
        conversation_id=conversation_id,
        barbershop_id=barbershop_id,
        system_type=system_type,
        client_info=ClientInfo(phone=client_phone).model_dump(),
        current_intent=IntentType.UNKNOWN.value,
        intent_confidence=0.0,
        previous_intents=[],
        conversation_stage=ConversationStage.INITIAL.value,
        turn_count=0,
        appointment_request=AppointmentRequest().model_dump(),
        scheduling_data=SchedulingData().model_dump(),
        agent_response="",
        response_type="text",
        guardrail_result=GuardrailResult().model_dump(),
        errors=[],
        last_error={},
        retrieved_knowledge=[],
        metadata={
            "created_at": datetime.utcnow().isoformat(),
            "agent_version": "1.0.0",
        },
    )
