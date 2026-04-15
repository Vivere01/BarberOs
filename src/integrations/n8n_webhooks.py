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
        # Base URL atualizada para incluir /webhook/ conforme novos requisitos
        self.base_url = "https://webhook.nexage.com.br/webhook"
        self._client = None
        
    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0) # Aumentado timeout para 15s
        return self._client

    async def post(self, endpoint: str, data: dict) -> dict:
        url = f"{self.base_url}/{endpoint}"
        logger.debug(f"CHAMANDO_WEBHOOK: {url}")
        
        client = self._get_client()
        
        try:
            response = await client.post(url, json=data)
            
            # Se der 404 na raiz /webhook/endpoint, tentamos sem o /webhook/ (legacy fallback)
            if response.status_code == 404 and "/webhook/" in url:
                legacy_url = url.replace("/webhook/", "/")
                logger.debug(f"TRYING_LEGACY_URL: {legacy_url}")
                response = await client.post(legacy_url, json=data)

            response.raise_for_status()
            
            if not response.content:
                return {"success": True, "message": "Operação realizada sem retorno"}
                
            return response.json()
        except Exception as e:
            logger.error(f"ERRO_WEBHOOK_{endpoint.upper()}: {str(e)}")
            return {"error": str(e), "success": False, "details": "N8N offline ou endpoint inválido"}

    async def buscar_horarios(self, start: str, end: str, id_agenda: Any, id_filial: Any, duration: int, 
                             inbox: Optional[str] = None, contact_id: Optional[str] = None, 
                             conversation_id: Optional[str] = None, amostras: int = 5):
        data = {
            "periodo_inicio": start,
            "periodo_fim": end,
            "id_agenda": str(id_agenda),
            "tamanho_janela_minutos": duration,
            "granularidade": 15,
            "amostras": amostras,
            "id_filial": str(id_filial),
            "inbox_do_cliente": inbox,
            "contact_id": contact_id,
            "conversation_id": conversation_id
        }
        # Remove chaves com None para evitar confusão no N8N se necessário
        data = {k: v for k, v in data.items() if v is not None}
        return await self.post("buscar_horarios", data)

    async def criar_agendamento(self, start: str, duration: int, title: str, desc: str, 
                               id_agenda: Any, services: List[Any], id_filial: Any,
                               id_cliente: Optional[str] = None, inbox: Optional[str] = None,
                               contact_id: Optional[str] = None, conversation_id: Optional[str] = None):
        data = {
            "evento_inicio": start,
            "duracao_minutos": duration,
            "titulo": title,
            "descricao": desc,
            "id_agenda": str(id_agenda),
            "id_servicos": services,
            "id_cliente_cashbarber": id_cliente,
            "id_filial": str(id_filial),
            "inbox_do_cliente": inbox,
            "contact_id": contact_id,
            "conversation_id": conversation_id
        }
        data = {k: v for k, v in data.items() if v is not None}
        return await self.post("criar_agendamento", data)

    async def buscar_agendamento_contato(self, start: str, end: str, id_agenda: Any, id_filial: Any,
                                       id_cliente: Optional[str] = None, inbox: Optional[str] = None,
                                       duration: int = 30):
        data = {
            "periodo_inicio": start,
            "periodo_fim": end,
            "id_agenda": str(id_agenda),
            "tamanho_janela_minutos": duration,
            "id_filial": str(id_filial),
            "id_cliente": id_cliente,
            "inbox_do_cliente": inbox
        }
        data = {k: v for k, v in data.items() if v is not None}
        return await self.post("buscar_agendamento_contato", data)

    async def desmarcar_agendamento(self, phone: str, message: str, id_agenda: Any, id_evento: str,
                                   inbox: Optional[str] = None, contact_id: Optional[str] = None,
                                   conversation_id: Optional[str] = None):
        data = {
            "telefone": phone,
            "mensagem": message,
            "id_agenda": str(id_agenda),
            "id_evento": id_evento,
            "inbox_do_cliente": inbox,
            "contact_id": contact_id,
            "conversation_id": conversation_id
        }
        data = {k: v for k, v in data.items() if v is not None}
        return await self.post("desmarcar_agendamento", data)

    async def cancelar_agendamento(self, *args, **kwargs):
        """Legacy alias para desmarcar_agendamento"""
        return await self.desmarcar_agendamento(*args, **kwargs)

    async def buscar_cliente(self, phone: str):
        data = {"telefone": phone}
        return await self.post("buscar_cadastro_cliente", data)

    async def criar_cliente(self, phone: str, name: str, email: Optional[str] = None):
        data = {
            "telefone": phone,
            "nome": name,
            "email": email
        }
        return await self.post("criar_cadastro_cliente", data)
