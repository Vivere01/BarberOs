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
        # Tenta a URL direta e a URL com prefixo /webhook/ que é comum no n8n
        url = f"{self.base_url}/{endpoint}"
        
        logger.debug(f"CHAMANDO_WEBHOOK: {url}")
        
        try:
            async with httpx.AsyncClient() as client:
                # Timeout curto de 7 segundos para evitar o vácuo
                response = await client.post(url, json=data, timeout=7.0)
                
                if response.status_code == 404:
                    # Tenta fallback para /webhook/endpoint se der 404
                    url_fallback = f"{self.base_url}/webhook/{endpoint}"
                    logger.debug(f"TRYING_FALLBACK_URL: {url_fallback}")
                    response = await client.post(url_fallback, json=data, timeout=7.0)

                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"ERRO_WEBHOOK_{endpoint.upper()}: {str(e)}")
            return {"error": str(e), "success": False, "details": "N8N offline ou endpoint inválido"}

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

    async def buscar_cliente(self, phone: str):
        data = {"telefone": phone}
        return await self._post("buscar_cadastro_cliente", data)

    async def criar_cliente(self, phone: str, name: str, email: Optional[str] = None):
        data = {
            "telefone": phone,
            "nome": name,
            "email": email
        }
        return await self._post("criar_cadastro_cliente", data)
