"""
BarberOS - Router Node (Classificação de Intenção)
====================================================
Nó responsável por classificar a intenção do cliente
usando output estruturado (JSON) para evitar alucinação.

A classificação usa uma lista FECHADA de intenções.
O LLM não pode inventar novas categorias.
"""
import json
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.agent.state import AgentState, IntentType, ConversationStage
from src.agent.prompts import INTENT_CLASSIFICATION_PROMPT
from src.config.logging_config import get_logger
from src.config.settings import get_settings

logger = get_logger("agent.router")


async def route_intent(state: AgentState) -> dict:
    """
    Classifica a intenção da última mensagem do cliente.

    ESTRATÉGIA ANTI-ALUCINAÇÃO:
    1. Usa output estruturado (JSON schema)
    2. Lista fechada de intenções (enum)
    3. Exige confidence score
    4. Fallback para humano se confiança baixa
    """
    settings = get_settings()

    # Pega a última mensagem do usuário
    last_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage) or (hasattr(msg, "type") and msg.type == "human"):
            last_message = msg.content if hasattr(msg, "content") else str(msg)
            break

    if not last_message:
        logger.warning(
            "No user message found",
            conversation_id=state["conversation_id"],
        )
        return {
            "current_intent": IntentType.UNKNOWN.value,
            "intent_confidence": 0.0,
            "conversation_stage": ConversationStage.ERROR.value,
        }

    # Classificação com output estruturado
    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=0.0,  # Temperatura ZERO para classificação
        api_key=settings.openai_api_key,
    )

    prompt = INTENT_CLASSIFICATION_PROMPT.format(message=last_message)

    try:
        response = await llm.ainvoke([
            SystemMessage(content="Você é um classificador de intenções. Responda APENAS em JSON válido."),
            HumanMessage(content=prompt),
        ])

        # Parse do JSON
        result = _parse_intent_response(response.content)
        intent = result.get("intent", IntentType.UNKNOWN.value)
        confidence = result.get("confidence", 0.0)
        entities = result.get("extracted_entities", {})

        # Valida que a intenção está na lista permitida
        valid_intents = {e.value for e in IntentType}
        if intent not in valid_intents:
            logger.warning(
                "LLM returned invalid intent, defaulting to unknown",
                returned_intent=intent,
                conversation_id=state["conversation_id"],
            )
            intent = IntentType.UNKNOWN.value
            confidence = 0.0

        # Se confiança muito baixa, encaminha para humano
        if confidence < settings.human_handoff_confidence_threshold:
            logger.info(
                "Low confidence, flagging for human handoff",
                intent=intent,
                confidence=confidence,
                conversation_id=state["conversation_id"],
            )
            intent = IntentType.HUMAN_HANDOFF.value

        # Atualiza appointment_request com entidades extraídas
        appointment_request = dict(state.get("appointment_request", {}))
        for field in ["service", "professional", "date", "time"]:
            if entities.get(field):
                appointment_request[field] = entities[field]

        # Recalcula missing_fields
        required = ["service", "professional", "date", "time"]
        missing = [f for f in required if not appointment_request.get(f)]
        appointment_request["missing_fields"] = missing
        appointment_request["is_complete"] = len(missing) == 0

        # Determina estágio da conversa
        stage = _determine_stage(intent, appointment_request)

        # Atualiza intents anteriores
        previous = list(state.get("previous_intents", []))
        if state.get("current_intent") and state["current_intent"] != IntentType.UNKNOWN.value:
            previous.append(state["current_intent"])

        logger.info(
            "Intent classified",
            intent=intent,
            confidence=confidence,
            entities=entities,
            conversation_id=state["conversation_id"],
        )

        return {
            "current_intent": intent,
            "intent_confidence": confidence,
            "previous_intents": previous,
            "conversation_stage": stage,
            "appointment_request": appointment_request,
            "turn_count": state.get("turn_count", 0) + 1,
        }

    except Exception as e:
        logger.error(
            "Intent classification failed",
            error=str(e),
            conversation_id=state["conversation_id"],
            component="router",
        )
        return {
            "current_intent": IntentType.HUMAN_HANDOFF.value,
            "intent_confidence": 0.0,
            "conversation_stage": ConversationStage.ERROR.value,
            "errors": state.get("errors", []) + [{
                "error_id": f"router_{datetime.utcnow().timestamp()}",
                "error_type": "intent_classification",
                "error_message": str(e),
                "node_name": "route_intent",
                "timestamp": datetime.utcnow().isoformat(),
                "recovery_action": "human_handoff",
            }],
        }


def _parse_intent_response(content: str) -> dict:
    """Parse JSON response, handling markdown code blocks."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1])

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Failed to parse intent JSON", raw_content=content[:200])
        return {
            "intent": IntentType.UNKNOWN.value,
            "confidence": 0.0,
            "extracted_entities": {},
        }


def _determine_stage(intent: str, appointment: dict) -> str:
    """Determina o estágio baseado na intenção e dados coletados."""
    if intent in (IntentType.GREETING.value, IntentType.FAQ.value):
        return ConversationStage.INITIAL.value
    elif intent in (IntentType.COMPLAINT.value, IntentType.HUMAN_HANDOFF.value, IntentType.UNKNOWN.value):
        return ConversationStage.HANDOFF.value
    elif intent in (
        IntentType.SCHEDULE_APPOINTMENT.value,
        IntentType.RESCHEDULE_APPOINTMENT.value,
    ):
        if appointment.get("is_complete"):
            return ConversationStage.CONFIRMING.value
        return ConversationStage.COLLECTING_INFO.value
    elif intent == IntentType.CANCEL_APPOINTMENT.value:
        return ConversationStage.CONFIRMING.value
    else:
        return ConversationStage.INITIAL.value
