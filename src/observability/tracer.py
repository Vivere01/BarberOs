"""
BarberOS - Observability & Tracing
=====================================
Rastreamento completo de cada conversa para debugging.
Integra com LangSmith para visualização de traces.

Cada conversa gera um trace que contém:
- Todas as mensagens
- Decisão de roteamento
- Dados buscados nos sistemas
- Resultado da validação
- Erros encontrados
- Tempo de execução de cada nó
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Optional

import structlog

from src.config.logging_config import get_logger
from src.config.settings import get_settings

logger = get_logger("observability.tracer")


class ConversationTrace:
    """
    Trace de uma conversa completa.
    Armazena todos os dados para debugging pós-incidente.
    """

    def __init__(
        self,
        conversation_id: str,
        barbershop_id: str,
    ):
        self.conversation_id = conversation_id
        self.barbershop_id = barbershop_id
        self.started_at = datetime.utcnow()
        self.ended_at: Optional[datetime] = None
        self.steps: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}

    def add_step(
        self,
        node_name: str,
        duration_ms: float,
        input_data: Optional[dict] = None,
        output_data: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        """Registra um passo da execução."""
        step = {
            "node": node_name,
            "timestamp": datetime.utcnow().isoformat(),
            "duration_ms": round(duration_ms, 2),
            "success": error is None,
        }

        if input_data:
            step["input_preview"] = str(input_data)[:500]
        if output_data:
            step["output_preview"] = str(output_data)[:500]
        if error:
            step["error"] = error
            self.errors.append({
                "node": node_name,
                "error": error,
                "timestamp": step["timestamp"],
            })

        self.steps.append(step)

    def finish(self) -> dict[str, Any]:
        """Finaliza o trace e retorna resumo."""
        self.ended_at = datetime.utcnow()
        total_ms = (self.ended_at - self.started_at).total_seconds() * 1000

        summary = {
            "conversation_id": self.conversation_id,
            "barbershop_id": self.barbershop_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "total_duration_ms": round(total_ms, 2),
            "steps_count": len(self.steps),
            "errors_count": len(self.errors),
            "steps": self.steps,
            "errors": self.errors,
            "metrics": self.metrics,
        }

        # Log o trace completo
        if self.errors:
            logger.error(
                "Conversation trace completed with errors",
                **{k: v for k, v in summary.items() if k != "steps"},
            )
        else:
            logger.info(
                "Conversation trace completed",
                conversation_id=self.conversation_id,
                total_ms=round(total_ms, 2),
                steps=len(self.steps),
            )

        return summary


# Trace ativo por conversa
_active_traces: dict[str, ConversationTrace] = {}


@contextmanager
def trace_conversation(
    conversation_id: str,
    barbershop_id: str,
) -> Generator[ConversationTrace, None, None]:
    """
    Context manager para rastrear uma conversa.

    Uso:
        with trace_conversation(conv_id, barber_id) as trace:
            # executa o grafo
            trace.add_step("router", 50.0, ...)
    """
    trace = ConversationTrace(conversation_id, barbershop_id)
    _active_traces[conversation_id] = trace

    try:
        yield trace
    finally:
        trace.finish()
        _active_traces.pop(conversation_id, None)


def get_active_trace(conversation_id: str) -> Optional[ConversationTrace]:
    """Retorna trace ativo de uma conversa."""
    return _active_traces.get(conversation_id)


class MetricsCollector:
    """
    Coleta métricas para monitoramento:
    - Total de conversas
    - Taxa de alucinação
    - Taxa de handoff para humano
    - Tempo médio de resposta
    - Erros por tipo
    """

    def __init__(self):
        self.total_conversations: int = 0
        self.total_hallucinations: int = 0
        self.total_handoffs: int = 0
        self.total_errors: int = 0
        self.response_times_ms: list[float] = []
        self.intent_counts: dict[str, int] = {}
        self.error_counts: dict[str, int] = {}

    def record_conversation(
        self,
        duration_ms: float,
        intent: str,
        hallucination: bool = False,
        handoff: bool = False,
        error: Optional[str] = None,
    ) -> None:
        self.total_conversations += 1
        self.response_times_ms.append(duration_ms)

        if hallucination:
            self.total_hallucinations += 1
        if handoff:
            self.total_handoffs += 1
        if error:
            self.total_errors += 1
            self.error_counts[error] = self.error_counts.get(error, 0) + 1

        self.intent_counts[intent] = self.intent_counts.get(intent, 0) + 1

    def get_summary(self) -> dict[str, Any]:
        avg_time = (
            sum(self.response_times_ms) / len(self.response_times_ms)
            if self.response_times_ms
            else 0
        )

        return {
            "total_conversations": self.total_conversations,
            "hallucination_rate": (
                self.total_hallucinations / max(self.total_conversations, 1)
            ),
            "handoff_rate": (
                self.total_handoffs / max(self.total_conversations, 1)
            ),
            "error_rate": (
                self.total_errors / max(self.total_conversations, 1)
            ),
            "avg_response_time_ms": round(avg_time, 2),
            "intent_distribution": self.intent_counts,
            "error_types": self.error_counts,
        }


# Singleton global
metrics = MetricsCollector()
