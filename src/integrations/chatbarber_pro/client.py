"""
BarberOS - ChatBarber PRO API Client
=====================================
Client configurado para a arquitetura oficial do ChatBarber PRO:
Padrão: https://{domain}/api/v1/{owner_id}/{endpoint}

IMPORTANTE: A API retorna dados encapsulados:
  - GET /services  → { count: N, services: [...] }
  - GET /clients   → { count: N, clients: [...] }
  - GET /staff     → { count: N, staff: [...] }
  - POST /clients  → { success: true, client: { id, ... } }

Este client desempacota automaticamente esses envelopes.
"""
import httpx
import logging
import asyncio
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ChatBarberProClient:
    def __init__(self, api_key: Optional[str] = None, owner_id: Optional[str] = None, base_url: str = "https://www.chatbarber.pro", **kwargs):
        """
        Inicia o cliente para o ChatBarber PRO.
        Suporta tanto api_key quanto api_token para compatibilidade.
        """
        self.api_key = api_key or kwargs.get("api_token")
        self.owner_id = owner_id
        self.base_url = (base_url or "https://www.chatbarber.pro").rstrip("/")
        
        if not self.api_key:
            logger.warning("ChatBarberProClient: API Key ausente.")
            
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None):
        """Método base para chamadas HTTP seguindo o padrão /api/v1/{owner_id}/{endpoint}."""
        if not self.owner_id:
            logger.error(f"CHATBARBERPRO_ERROR: Sem owner_id para o endpoint {endpoint}")
            return {"error": "Configuração incompleta (owner_id ausente)"}

        url = f"{self.base_url}/api/v1/{self.owner_id}/{endpoint}"
        logger.info(f"CHATBARBERPRO_REQUEST: {method} {url}")
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.request(method, url, json=data, params=params, headers=self.headers)
                
                if response.status_code >= 400:
                    logger.error(f"CHATBARBERPRO_ERROR ({response.status_code}): {endpoint} -> {response.text[:200]}")
                    try:
                        return response.json()
                    except:
                        return {"error": f"Erro HTTP {response.status_code}", "detail": response.text[:100]}
                
                return response.json()
            except Exception as e:
                logger.error(f"CHATBARBERPRO_CONNECTION_ERROR: {str(e)} | URL: {url}")
                return {"error": f"Erro de conexão com o servidor ChatBarber PRO: {str(e)}"}

    def _unwrap(self, res: Any, key: str) -> list:
        """
        Desempacota resposta da API.
        A API retorna { count: N, <key>: [...] } — extrai a lista interna.
        """
        if isinstance(res, list):
            return res
        if isinstance(res, dict):
            if "error" in res:
                logger.warning(f"CHATBARBERPRO_UNWRAP: Resposta com erro para '{key}': {res.get('error')}")
                return []
            if key in res:
                inner = res[key]
                return inner if isinstance(inner, list) else []
            if res.get("id"):
                return [res]
        return []

    # --- Endpoints ---

    async def list_plans(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/plans → desempacota { count, plans: [...] }"""
        res = await self._request("GET", "plans")
        return self._unwrap(res, "plans")

    async def list_clients(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/clients"""
        res = await self._request("GET", "clients")
        return self._unwrap(res, "clients")

    async def search_client_by_phone(self, phone: str) -> Dict:
        """Busca um cliente pelo telefone e retorna o perfil completo (incluindo assinaturas)."""
        clean_target = "".join(filter(str.isdigit, phone))
        res = await self._request("GET", "clients", params={"phone": clean_target})
        clients_list = self._unwrap(res, "clients")
        
        if len(clients_list) > 0:
            for c in clients_list:
                c_phone = "".join(filter(str.isdigit, str(c.get("phone", ""))))
                if clean_target in c_phone or c_phone in clean_target:
                    return {"found": True, **c}
        return {"found": False}

    async def get_client_by_phone(self, phone: str) -> Optional[Dict]:
        """Versão legada."""
        res = await self.search_client_by_phone(phone)
        return res if res.get("found") else None

    async def create_client(self, *args, **kwargs) -> Dict:
        """POST /api/v1/{owner_id}/clients"""
        if args and isinstance(args[0], dict):
            payload = args[0]
        else:
            payload = {
                "name": kwargs.get("name"),
                "phone": kwargs.get("phone"),
                "email": kwargs.get("email"),
                "birth_date": kwargs.get("birth_date") or kwargs.get("data_nascimento")
            }
        res = await self._request("POST", "clients", data=payload)
        if isinstance(res, dict) and "client" in res:
            return res["client"]
        return res

    async def list_appointments(self, date: Optional[str] = None, **kwargs) -> Dict:
        """GET /api/v1/{owner_id}/appointments"""
        date_val = date or kwargs.get("date_filter")
        params = {"date": date_val} if date_val else {}
        res = await self._request("GET", "appointments", params=params)
        if isinstance(res, list): return {"appointments": res}
        if isinstance(res, dict) and "appointments" in res: return res
        return {"appointments": []}

    async def create_appointment(self, *args, **kwargs) -> Dict:
        """POST /api/v1/{owner_id}/appointments"""
        if args and isinstance(args[0], dict):
            payload = args[0]
        else:
            payload = {
                "clientId": kwargs.get("client_id") or kwargs.get("clientId"),
                "serviceId": kwargs.get("service_id") or kwargs.get("serviceId"),
                "staffId": kwargs.get("staff_id") or kwargs.get("staffId"),
                "storeId": kwargs.get("store_id") or kwargs.get("storeId"),
                "scheduledAt": kwargs.get("scheduled_at") or kwargs.get("data_isostring"),
                "notes": kwargs.get("notes", "Agendamento via IA Helena")
            }
        res = await self._request("POST", "appointments", data=payload)
        if isinstance(res, dict) and res.get("success"):
            return {"status": "success", **res}
        return res

    async def list_services(self) -> List[Dict]:
        res = await self._request("GET", "services")
        return self._unwrap(res, "services")

    async def list_staff(self) -> List[Dict]:
        res = await self._request("GET", "staff")
        return self._unwrap(res, "staff")

    async def list_stores(self) -> List[Dict]:
        res = await self._request("GET", "stores")
        return self._unwrap(res, "stores")
