"""
BarberOS - ChatBarber PRO API Client
=====================================
Client configurado para a arquitetura oficial do ChatBarber PRO:
Padrão: https://{domain}/api/v1/{owner_id}/{endpoint}
"""
import httpx
import logging
import asyncio
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ChatBarberProClient:
    def __init__(self, api_key: str, owner_id: str, base_url: str = "https://www.chatbarber.pro"):
        """
        Inicia o cliente para o ChatBarber PRO.
        :param api_key: Token Bearer de autenticação.
        :param owner_id: ID da barbearia usado na URL.
        :param base_url: URL base (ex: https://vossa-plataforma.com.br).
        """
        self.api_key = api_key
        self.owner_id = owner_id
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None):
        """Método base para chamadas HTTP seguindo o padrão /api/v1/{owner_id}/{endpoint}."""
        url = f"{self.base_url}/api/v1/{self.owner_id}/{endpoint}"
        
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                response = await client.request(method, url, json=data, params=params, headers=self.headers)
                
                if response.status_code >= 400:
                    logger.error(f"CHATBARBERPRO_ERROR ({response.status_code}): {endpoint} -> {response.text[:200]}")
                    return None
                
                return response.json()
            except Exception as e:
                logger.error(f"CHATBARBERPRO_CONNECTION_ERROR: {str(e)}")
                return None

    # --- Endpoints da sua Documentação ---

    async def list_clients(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/clients"""
        res = await self._request("GET", "clients")
        return res if isinstance(res, list) else []

    async def create_client(self, client_data: Dict) -> Optional[Dict]:
        """POST /api/v1/{owner_id}/clients"""
        return await self._request("POST", "clients", data=client_data)

    async def list_appointments(self, date: Optional[str] = None) -> List[Dict]:
        """GET /api/v1/{owner_id}/appointments"""
        params = {"date": date} if date else {}
        res = await self._request("GET", "appointments", params=params)
        return res if isinstance(res, list) else []

    async def create_appointment(self, appointment_data: Dict) -> Optional[Dict]:
        """POST /api/v1/{owner_id}/appointments"""
        return await self._request("POST", "appointments", data=appointment_data)

    async def list_services(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/services"""
        res = await self._request("GET", "services")
        return res if isinstance(res, list) else []

    async def list_staff(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/staff"""
        res = await self._request("GET", "staff")
        return res if isinstance(res, list) else []

    async def list_stores( self) -> List[Dict]:
        """GET /api/v1/{owner_id}/stores"""
        res = await self._request("GET", "stores")
        return res if isinstance(res, list) else []

    async def get_ai_context(self) -> Optional[Dict]:
        """GET /api/v1/{owner_id}/ai-context"""
        return await self._request("GET", "ai-context")

    # --- Utilitários Helena ---

    async def get_client_by_phone(self, phone: str) -> Optional[Dict]:
        """Busca cliente pelo telefone na lista de clientes."""
        clients = await self.list_clients()
        # Limpa o telefone para comparação
        clean_phone = "".join(filter(str.isdigit, phone))
        
        for c in clients:
            c_phone = "".join(filter(str.isdigit, str(c.get("phone", ""))))
            if clean_phone in c_phone or c_phone in clean_phone:
                return c
        return None
