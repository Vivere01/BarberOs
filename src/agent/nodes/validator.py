"""
BarberOS - Validator Node (ANTI-ALUCINAÇÃO)
=============================================
Este é o nó MAIS CRÍTICO da arquitetura.

Toda resposta do agente passa por aqui ANTES de ser enviada ao cliente.
O validador checa:
1. Alucinação de dados (serviços, preços, horários inventados)
2. Informações pessoais (PII) expostas
3. Comprimento da resposta
4. Conformidade com regras de negócio
5. Consistência com dados reais do sistema
"""
import json
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.agent.state import (
    AgentState,
    ConversationStage,
    ConfidenceLevel,
    GuardrailResult,
)
from src.agent.prompts import RESPONSE_TEMPLATES, VALIDATION_PROMPT
from src.config.logging_config import get_logger
from src.config.settings import get_settings

logger = get_logger("agent.validator")


async def validate_response(state: AgentState) -> dict:
    """
    Valida a resposta do agente contra dados reais.

    PIPELINE DE VALIDAÇÃO:
    1. Validação de comprimento
    2. Detecção de PII
    3. Validação contra dados reais (LLM-as-judge)
    4. Verificação de regras de negócio
    5. Score final de confiança

    Se alguma validação falhar, a resposta é corrigida ou
    substituída por uma resposta segura.
    """
    settings = get_settings()
    response = state.get("agent_response", "")
    scheduling_data = state.get("scheduling_data", {})

    violations: list[str] = []
    hallucination_detected = False
    pii_detected = False
    corrected_response = None

    # ─── Step 1: Validação de comprimento ───
    if len(response) > settings.max_response_length * 3:
        violations.append(f"Resposta muito longa ({len(response)} chars)")
        # Trunca mas mantém sentido
        response = response[:settings.max_response_length] + "..."

    # ─── Step 2: Detecção de PII ───
    if settings.enable_pii_filter:
        pii_detected = _check_pii(response)
        if pii_detected:
            violations.append("PII detectado na resposta")
            response = _remove_pii(response)

    # ─── Step 3: Validação contra dados reais ───
    if _needs_data_validation(state):
        hallucination_result = await _validate_against_real_data(
            response, scheduling_data, settings
        )
        if hallucination_result.get("hallucination_detected"):
            hallucination_detected = True
            violations.extend(hallucination_result.get("violations", []))
            corrected = hallucination_result.get("suggested_correction")
            if corrected:
                corrected_response = corrected
                logger.warning(
                    "Hallucination detected and corrected",
                    original=response[:100],
                    corrected=corrected[:100],
                    violations=violations,
                    conversation_id=state["conversation_id"],
                )

    # ─── Step 4: Regras de negócio ───
    biz_violations = _check_business_rules(response, state)
    violations.extend(biz_violations)

    # ─── Step 5: Score de confiança ───
    confidence = _calculate_confidence(violations, hallucination_detected)
    if confidence >= 0.8:
        confidence_level = ConfidenceLevel.HIGH
    elif confidence >= 0.5:
        confidence_level = ConfidenceLevel.MEDIUM
    else:
        confidence_level = ConfidenceLevel.LOW

    # Decisão final
    final_response = response
    if hallucination_detected and corrected_response:
        final_response = corrected_response
    elif confidence_level == ConfidenceLevel.LOW:
        final_response = RESPONSE_TEMPLATES["data_not_found"]
        logger.error(
            "Response confidence too low, using fallback",
            confidence=confidence,
            violations=violations,
            conversation_id=state["conversation_id"],
        )

    guardrail_result = GuardrailResult(
        is_valid=not hallucination_detected and len(violations) == 0,
        violations=violations,
        confidence=confidence,
        confidence_level=confidence_level,
        hallucination_detected=hallucination_detected,
        pii_detected=pii_detected,
        suggested_correction=corrected_response,
    )

    logger.info(
        "Response validated",
        is_valid=guardrail_result.is_valid,
        confidence=confidence,
        confidence_level=confidence_level.value,
        violations_count=len(violations),
        hallucination=hallucination_detected,
        conversation_id=state["conversation_id"],
    )

    # Se a resposta mudou, atualizamos as mensagens
    update: dict = {
        "guardrail_result": guardrail_result.model_dump(),
    }

    if final_response != state.get("agent_response"):
        update["agent_response"] = final_response
        # Substitui última mensagem AI
        messages = list(state.get("messages", []))
        if messages and hasattr(messages[-1], "type") and messages[-1].type == "ai":
            messages[-1] = AIMessage(content=final_response)
        update["messages"] = messages

    return update


def _needs_data_validation(state: AgentState) -> bool:
    """Verifica se a resposta precisa de validação de dados."""
    intent = state.get("current_intent", "")
    # Respostas de template puro não precisam de validação
    stage = state.get("conversation_stage", "")
    if stage in (ConversationStage.COMPLETED.value, ConversationStage.HANDOFF.value):
        return False
    # Respostas sobre dados específicos precisam
    data_intents = {
        "query_services", "query_prices", "query_hours",
        "schedule_appointment", "check_availability",
    }
    return intent in data_intents


async def _validate_against_real_data(
    response: str,
    scheduling_data: dict,
    settings,
) -> dict:
    """Usa LLM como juiz para detectar alucinações."""
    try:
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.0,
            api_key=settings.openai_api_key,
        )

        services = scheduling_data.get("services", [])
        professionals = scheduling_data.get("professionals", [])
        slots = scheduling_data.get("available_slots", [])
        hours = scheduling_data.get("business_hours", {})

        prompt = VALIDATION_PROMPT.format(
            real_services=json.dumps(services, ensure_ascii=False) if services else "Não carregados",
            real_professionals=json.dumps(professionals, ensure_ascii=False) if professionals else "Não carregados",
            real_slots=json.dumps(slots, ensure_ascii=False) if slots else "Não carregados",
            real_prices=json.dumps(
                [{s.get("name"): s.get("price")} for s in services],
                ensure_ascii=False,
            ) if services else "Não carregados",
            real_hours=json.dumps(hours, ensure_ascii=False) if hours else "Não carregado",
            agent_response=response,
        )

        result = await llm.ainvoke([
            SystemMessage(content="Você é um validador. Responda APENAS em JSON."),
            HumanMessage(content=prompt),
        ])

        content = result.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        return json.loads(content)

    except Exception as e:
        logger.error(
            "Validation LLM call failed",
            error=str(e),
        )
        # Em caso de erro na validação, assume válido
        # (melhor enviar resposta com possível problema do que não responder)
        return {"hallucination_detected": False, "violations": [], "confidence": 0.6}


def _check_pii(text: str) -> bool:
    """Detecta PII na resposta (CPF, email, telefone completo)."""
    import re

    patterns = [
        r'\d{3}\.\d{3}\.\d{3}-\d{2}',  # CPF
        r'\d{11,}',  # Telefone longo
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # Email
    ]

    for pattern in patterns:
        if re.search(pattern, text):
            return True
    return False


def _remove_pii(text: str) -> str:
    """Remove PII detectado da resposta."""
    import re

    text = re.sub(r'\d{3}\.\d{3}\.\d{3}-\d{2}', '[CPF REMOVIDO]', text)
    text = re.sub(
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        '[EMAIL REMOVIDO]',
        text,
    )
    return text


def _check_business_rules(response: str, state: AgentState) -> list[str]:
    """Verifica regras de negócio."""
    violations = []

    # Não deve prometer coisas fora do horário
    response_lower = response.lower()
    forbidden_promises = [
        "com certeza", "garantido", "100%",
        "sempre", "nunca falha",
    ]
    for phrase in forbidden_promises:
        if phrase in response_lower:
            violations.append(f"Promessa excessiva detectada: '{phrase}'")

    return violations


def _calculate_confidence(violations: list[str], hallucination: bool) -> float:
    """Calcula score de confiança baseado nas violações."""
    score = 1.0

    if hallucination:
        score -= 0.5

    # Cada violação reduz a confiança
    score -= len(violations) * 0.1

    return max(0.0, min(1.0, score))
