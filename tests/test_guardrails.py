"""
BarberOS - Testes do Sistema de Guardrails
============================================
Testes para garantir que o sistema anti-alucinação funciona.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.agent.nodes.validator import (
    validate_response,
    _check_pii,
    _remove_pii,
    _check_business_rules,
    _calculate_confidence,
)
from src.agent.state import AgentState, IntentType, ConversationStage, create_initial_state


class TestPIIDetection:
    """Testes de detecção de informações pessoais."""

    def test_detect_cpf(self):
        assert _check_pii("Seu CPF é 123.456.789-00") is True

    def test_detect_email(self):
        assert _check_pii("Email: teste@example.com") is True

    def test_no_pii(self):
        assert _check_pii("Olá, tudo bem?") is False

    def test_remove_cpf(self):
        result = _remove_pii("CPF: 123.456.789-00")
        assert "123.456.789-00" not in result
        assert "[CPF REMOVIDO]" in result

    def test_remove_email(self):
        result = _remove_pii("Email: teste@example.com")
        assert "teste@example.com" not in result
        assert "[EMAIL REMOVIDO]" in result


class TestBusinessRules:
    """Testes de regras de negócio."""

    def test_detect_excessive_promises(self):
        state = create_initial_state("test", "test", "cashbarber", "119999")
        violations = _check_business_rules("Com certeza, garantido!", state)
        assert len(violations) > 0

    def test_normal_response_passes(self):
        state = create_initial_state("test", "test", "cashbarber", "119999")
        violations = _check_business_rules("Temos horários disponíveis amanhã.", state)
        assert len(violations) == 0


class TestConfidenceCalculation:
    """Testes de cálculo de confiança."""

    def test_perfect_confidence(self):
        assert _calculate_confidence([], False) == 1.0

    def test_hallucination_drops_confidence(self):
        assert _calculate_confidence([], True) == 0.5

    def test_violations_reduce_confidence(self):
        violations = ["violation1", "violation2"]
        result = _calculate_confidence(violations, False)
        assert result == 0.8

    def test_hallucination_and_violations(self):
        violations = ["violation1"]
        result = _calculate_confidence(violations, True)
        assert result == 0.4

    def test_minimum_confidence(self):
        violations = ["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10", "v11"]
        result = _calculate_confidence(violations, True)
        assert result == 0.0


class TestRouterIntentValidation:
    """Testes para validar que o router não aceita intenções inválidas."""

    def test_all_intents_are_defined(self):
        """Verifica que todas as intenções estão no enum."""
        expected = {
            "greeting", "schedule_appointment", "cancel_appointment",
            "reschedule_appointment", "check_availability", "check_appointment",
            "query_services", "query_prices", "query_hours", "query_location",
            "faq", "complaint", "human_handoff", "unknown",
        }
        actual = {e.value for e in IntentType}
        assert expected == actual

    def test_invalid_intent_not_in_enum(self):
        """Garante que intenções inventadas não existem."""
        assert "make_payment" not in {e.value for e in IntentType}
        assert "order_food" not in {e.value for e in IntentType}


class TestInitialState:
    """Testes do estado inicial."""

    def test_create_initial_state(self):
        state = create_initial_state(
            conversation_id="test-123",
            barbershop_id="barber-001",
            system_type="cashbarber",
            client_phone="11999999999",
        )

        assert state["conversation_id"] == "test-123"
        assert state["barbershop_id"] == "barber-001"
        assert state["system_type"] == "cashbarber"
        assert state["current_intent"] == "unknown"
        assert state["intent_confidence"] == 0.0
        assert state["turn_count"] == 0
        assert state["messages"] == []
        assert state["errors"] == []

    def test_initial_state_has_metadata(self):
        state = create_initial_state("test", "barber", "appbarber", "1199")
        assert "created_at" in state["metadata"]
        assert "agent_version" in state["metadata"]
