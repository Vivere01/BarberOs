"""
BarberOS - N8N Webhooks Integration
====================================
Implementação dos endpoints de agendamento, consulta e cancelamento.
"""
import httpx
from typing import Optional, List, Any
from src.config.settings import get_settings
from loguru import logger

class N8NWebhookClient:
    def __init__(self):
        self.base_url = "https://webhook.nexage.com.br"
        # Podemos adicionar um token no .env futuramente se necessário
        
    async def _post(self, endpoint: str, data: dict) -> dict:
        url = f"{self.base_url}/{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.debug(f"Chamando Webhook N8N: {url} com dados: {data}")
                response = await client.post(url, json=data)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Erro ao chamar Webhook {endpoint}: {str(e)}")
            return {"error": str(e), "success": False}

    async def buscar_horarios(self, start: str, end: str, id_agenda: int, id_filial: int, duration: int):
        data = {
            "periodo_inicio": start,
            "periodo_fim": end,
            "id_agenda": id_agenda,
            "id_filial": id_filial,
            "tamanho_janela_minutos": duration,
            "granularidade": 15
        }
        return await self._post("buscar_horarios", data)

    async def criar_agendamento(self, start: str, duration: int, title: str, desc: str, id_agenda: int, services: List[int], id_filial: int):
        data = {
            "evento_inicio": start,
            "duracao_minutos": duration,
            "titulo": title,
            "descricao": desc,
            "id_agenda": id_agenda,
            "id_servicos": services,
            "id_filial": id_filial
        }
        return await self._post("criar_agendamento", data)

    async def buscar_agendamento_contato(self, start: str, end: str, id_agenda: int, duration: int, id_filial: int):
        data = {
            "periodo_inicio": start,
            "periodo_fim": end,
            "id_agenda": id_agenda,
            "tamanho_janela_minutos": duration,
            "id_filial": id_filial
        }
        return await self._post("buscar_agendamento_contato", data)

    async def cancelar_agendamento(self, phone: str, message: str, id_agenda: int, id_evento: str):
        data = {
            "telefone": phone,
            "mensagem": message,
            "id_agenda": id_agenda,
            "id_evento": id_evento
        }
        return await self._post("cancelar_agendamento", data)
