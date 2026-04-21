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
        Se já for lista, retorna direto. Se for erro, retorna [].
        """
        if isinstance(res, list):
            return res
        if isinstance(res, dict):
            if "error" in res:
                logger.warning(f"CHATBARBERPRO_UNWRAP: Resposta com erro para '{key}': {res.get('error')}")
                return []
            # Tenta extrair pelo nome da chave (ex: "services", "clients", "staff")
            if key in res:
                inner = res[key]
                return inner if isinstance(inner, list) else []
            # Se for um dict sem a chave esperada, mas com dados, retorna como lista de 1
            if res.get("id"):
                return [res]
        return []

    # --- Endpoints ---

    async def list_clients(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/clients → desempacota { count, clients: [...] }"""
        res = await self._request("GET", "clients")
        return self._unwrap(res, "clients")

    async def search_client_by_phone(self, phone: str) -> Dict:
        """
        Busca um cliente pelo telefone.
        1. Tenta GET /clients?phone=... (se a API suportar filtro)
        2. Fallback: filtra manualmente na lista completa
        """
        clean_target = "".join(filter(str.isdigit, phone))
        
        # Tenta busca com parâmetro phone
        res = await self._request("GET", "clients", params={"phone": clean_target})
        
        # Desempacota a resposta (pode ser { count, clients: [...] } ou lista direta)
        clients_list = self._unwrap(res, "clients")
        
        # Se a API filtrou e retornou resultado
        if len(clients_list) > 0:
            # Verifica se algum realmente bate com o telefone buscado
            for c in clients_list:
                c_phone = "".join(filter(str.isdigit, str(c.get("phone", ""))))
                if clean_target in c_phone or c_phone in clean_target:
                    return {"found": True, "id": c.get("id"), "name": c.get("name")}
        
        # Se a busca acima não funcionou (API pode ter retornado todos os clientes sem filtrar)
        # Só faz fallback se a lista retornada não parece filtrada
        if len(clients_list) == 0:
            # Busca lista completa como último recurso
            all_clients = await self.list_clients()
            for c in all_clients:
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
        Resposta esperada: { success: true, client: { id, name, ... } }
        Retorna o objeto interno 'client' diretamente para facilitar extração do ID.
        """
        if args and isinstance(args[0], dict):
            payload = args[0]
        else:
            payload = {
                "name": kwargs.get("name"),
                "phone": kwargs.get("phone"),
                "birth_date": kwargs.get("birth_date") or kwargs.get("data_nascimento")
            }
        
        res = await self._request("POST", "clients", data=payload)
        
        # Desempacota: { success, client: { id, ... } } → retorna { id, ... }
        if isinstance(res, dict) and "client" in res:
            return res["client"]
        return res

    async def list_appointments(self, date: Optional[str] = None, **kwargs) -> Dict:
        """GET /api/v1/{owner_id}/appointments"""
        date_val = date or kwargs.get("date_filter")
        params = {"date": date_val} if date_val else {}
        res = await self._request("GET", "appointments", params=params)
        
        # Desempacota para formato esperado pelo engine
        if isinstance(res, list):
            return {"appointments": res}
        if isinstance(res, dict):
            # Se a API retornar { count, appointments: [...] }, já está ok
            if "appointments" in res:
                return res
            # Se retornar { error: ... }
            if "error" in res:
                return res
        return {"appointments": []}

    async def create_appointment(self, *args, **kwargs) -> Dict:
        """
        POST /api/v1/{owner_id}/appointments
        Mapeia nomes para o padrão da API.
        """
        if args and isinstance(args[0], dict):
            payload = args[0]
        else:
            # Transforma em inteiro as strings numéricas
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
                "serviceId": sid,
                "staffId": stid,
                "storeId": stid2,
                "scheduledAt": sched,
                "notes": kwargs.get("notes", "Agendamento via IA Helena")
            }
        
        logger.debug(f"CHATBARBERPRO_PAYLOAD: {payload}")
        
        res = await self._request("POST", "appointments", data=payload)
        
        # Desempacota: { success, appointment: { id, ... } } → adiciona indicador
        if isinstance(res, dict) and res.get("success"):
            return {"status": "success", **res}
        return res

    async def list_services(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/services → desempacota { count, services: [...] }"""
        res = await self._request("GET", "services")
        return self._unwrap(res, "services")

    async def list_staff(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/staff → desempacota { count, staff: [...] }"""
        res = await self._request("GET", "staff")
        return self._unwrap(res, "staff")

    async def list_stores(self) -> List[Dict]:
        """GET /api/v1/{owner_id}/stores → desempacota { count, stores: [...] }"""
        res = await self._request("GET", "stores")
        return self._unwrap(res, "stores")
