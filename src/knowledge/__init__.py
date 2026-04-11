"""
BarberOS - Knowledge Base Manager
====================================
Gerencia a base de conhecimento da barbearia para RAG.
Cada barbearia tem seu próprio contexto carregado no ChromaDB.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from src.config.logging_config import get_logger
from src.config.settings import get_settings

logger = get_logger("knowledge.loader")


class KnowledgeBaseManager:
    """
    Gerencia o knowledge base por barbearia.

    Cada barbearia tem:
    - Informações básicas (nome, endereço, horário)
    - FAQ personalizado
    - Regras de negócio
    - Histórico de promoções
    """

    def __init__(self):
        self._stores: dict[str, Any] = {}

    async def load_barbershop_knowledge(
        self,
        barbershop_id: str,
        config_path: Optional[str] = None,
    ) -> None:
        """Carrega knowledge base de uma barbearia."""
        if config_path:
            path = Path(config_path)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                self._stores[barbershop_id] = config
                logger.info(
                    "Knowledge base loaded from file",
                    barbershop_id=barbershop_id,
                    path=str(path),
                )
                return

        # Config padrão
        self._stores[barbershop_id] = self._get_default_config()
        logger.info(
            "Using default knowledge base",
            barbershop_id=barbershop_id,
        )

    def get_context(self, barbershop_id: str) -> dict[str, Any]:
        """Retorna contexto da barbearia para o prompt."""
        return self._stores.get(barbershop_id, self._get_default_config())

    def search(
        self,
        barbershop_id: str,
        query: str,
        top_k: int = 3,
    ) -> list[str]:
        """
        Busca na knowledge base.

        Por enquanto faz keyword matching.
        Em produção, usar ChromaDB com embeddings.
        """
        config = self._stores.get(barbershop_id, {})
        faq = config.get("faq", [])

        results = []
        query_lower = query.lower()

        for item in faq:
            question = item.get("question", "").lower()
            if any(word in question for word in query_lower.split()):
                results.append(item.get("answer", ""))

        return results[:top_k]

    def _get_default_config(self) -> dict[str, Any]:
        return {
            "barbershop_name": "Barbearia",
            "address": "",
            "phone": "",
            "business_hours": {},
            "faq": [
                {
                    "question": "Como agendar um horário?",
                    "answer": "Você pode agendar diretamente por aqui! Basta me dizer o serviço, profissional e horário desejado.",
                },
                {
                    "question": "Como cancelar um agendamento?",
                    "answer": "Você pode cancelar por aqui! Basta me avisar que deseja cancelar.",
                },
                {
                    "question": "Aceitam cartão?",
                    "answer": "Aceitamos todas as formas de pagamento: dinheiro, PIX, débito e crédito.",
                },
            ],
            "rules": {
                "max_advance_days": 30,
                "min_advance_minutes": 60,
                "cancellation_policy": "Cancelamentos devem ser feitos com pelo menos 2 horas de antecedência.",
            },
        }


# Singleton
knowledge_manager = KnowledgeBaseManager()
