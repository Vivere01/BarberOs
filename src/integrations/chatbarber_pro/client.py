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

    # --- Endpoints ---

    async def list_clients(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/clients"""
        res = await self._request("GET", "clients")
        if isinstance(res, dict) and "error" in res: return []
        return res if isinstance(res, list) else []

    async def search_client_by_phone(self, phone: str) -> Dict:
        """
        Alias para buscar um cliente pelo telefone.
        Tenta usar endpoint de busca se existir ou filtra na lista.
        """
        # Limpa o telefone
        clean_target = "".join(filter(str.isdigit, phone))
        
        # Primeiro, tenta um GET /clients?phone=... (se existir na API)
        res = await self._request("GET", "clients", params={"phone": clean_target})
        
        # Se retornar uma lista ou um objeto de cliente
        if isinstance(res, list) and len(res) > 0:
            return {"found": True, "id": res[0].get("id"), "name": res[0].get("name")}
        if isinstance(res, dict) and res.get("id"):
            return {"found": True, "id": res.get("id"), "name": res.get("name")}
            
        # Fallback: Varre a lista (ineficiente, mas seguro como último recurso)
        clients = await self.list_clients()
        for c in clients:
            c_phone = "".join(filter(str.isdigit, str(c.get("phone", ""))))
            if clean_target in c_phone or c_phone in clean_target:
                return {"found": True, "id": c.get("id"), "name": c.get("name")}
                
        return {"found": False}

    async def get_client_by_phone(self, phone: str) -> Optional[Dict]:
        """Versão legada para compatibilidade com full_engine."""
        res = await self.search_client_by_phone(phone)
        return res if res.get("found") else None

    async def create_client(self, *args, **kwargs) -> Dict:
        """
        POST /api/v1/{owner_id}/clients
        Suporta chamadas com dict (args[0]) ou argumentos nomeados (name, phone...).
        """
        if args and isinstance(args[0], dict):
            payload = args[0]
        else:
            payload = {
                "name": kwargs.get("name"),
                "phone": kwargs.get("phone"),
                "birth_date": kwargs.get("birth_date") or kwargs.get("data_nascimento")
            }
        return await self._request("POST", "clients", data=payload)

    async def list_appointments(self, date: Optional[str] = None, **kwargs) -> Dict:
        """GET /api/v1/{owner_id}/appointments"""
        date_val = date or kwargs.get("date_filter")
        params = {"date": date_val} if date_val else {}
        res = await self._request("GET", "appointments", params=params)
        # Padroniza retorno para dict conforme esperado pelo engine
        if isinstance(res, list):
            return {"appointments": res}
        return res if isinstance(res, dict) else {"appointments": []}

    async def create_appointment(self, *args, **kwargs) -> Dict:
        """
        POST /api/v1/{owner_id}/appointments
        Suporta chamadas com dict (args[0]) ou argumentos nomeados.
        Mapeia nomes para o padrão da API.
        """
        if args and isinstance(args[0], dict):
            payload = args[0]
        else:
            # Mapeia nomes do full_engine e chatbarber_pro_engine
            # Transforma em inteiro as strings que forem numéricas (para evitar erro 422 na API do backend)
            def _clean_id(val):
                if isinstance(val, str) and val.isdigit():
                    return int(val)
                return val

            cid = _clean_id(kwargs.get("client_id") or kwargs.get("clientId"))
            sid = _clean_id(kwargs.get("service_id") or kwargs.get("serviceId"))
            stid = _clean_id(kwargs.get("staff_id") or kwargs.get("staffId"))
            stid2 = _clean_id(kwargs.get("store_id") or kwargs.get("storeId"))
            sched = kwargs.get("scheduled_at") or kwargs.get("data_isostring") or kwargs.get("data_hora")
            
            payload = {
                "clientId": cid,
                "client_id": cid,
                "serviceId": sid,
                "service_id": sid,
                "staffId": stid,
                "staff_id": stid,
                "storeId": stid2,
                "store_id": stid2,
                "scheduledAt": sched,
                "scheduled_at": sched,
                "notes": kwargs.get("notes", "Agendamento via IA Helena")
            }
        
        # Log do payload para debug (sem dados sensíveis se possível, mas aqui IDs são seguros)
        logger.debug(f"CHATBARBERPRO_PAYLOAD: {payload}")
        
        return await self._request("POST", "appointments", data=payload)

    async def list_services(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/services"""
        res = await self._request("GET", "services")
        return res if isinstance(res, list) else []

    async def list_staff(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/staff"""
        res = await self._request("GET", "staff")
        return res if isinstance(res, list) else []

    async def list_stores(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/stores"""
        res = await self._request("GET", "stores")
        return res if isinstance(res, list) else []

