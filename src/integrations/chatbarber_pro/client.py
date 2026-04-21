"""
BarberOS - ChatBarber PRO API Client
=====================================
Client configurado para a arquitetura oficial do ChatBarber PRO.
"""
import httpx
import logging
import asyncio
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ChatBarberProClient:
    def __init__(self, api_key: Optional[str] = None, owner_id: Optional[str] = None, base_url: str = "https://www.chatbarber.pro", **kwargs):
        self.api_key = api_key or kwargs.get("api_token")
        self.owner_id = owner_id
        self.base_url = (base_url or "https://www.chatbarber.pro").rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None):
        if not self.owner_id:
            return {"error": "owner_id ausente"}
        url = f"{self.base_url}/api/v1/{self.owner_id}/{endpoint}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(method, url, json=data, params=params, headers=self.headers)
                return response.json()
            except Exception as e:
                return {"error": str(e)}

    def _unwrap(self, res: Any, key: str) -> list:
        if isinstance(res, list): return res
        if isinstance(res, dict):
            if key in res: return res[key]
            if res.get("id"): return [res]
        return []

    async def list_plans(self) -> List[Dict]:
        res = await self._request("GET", "plans")
        return self._unwrap(res, "plans")

    async def list_clients(self) -> List[Dict]:
        res = await self._request("GET", "clients")
        return self._unwrap(res, "clients")

    async def search_client_by_phone(self, phone: str) -> Dict:
        """Busca inteligente de cliente ignorando formatação e prefixos."""
        target = "".join(filter(str.isdigit, phone))
        if not target: return {"found": False}
        
        clients = await self.list_clients()
        for c in clients:
            c_phone = "".join(filter(str.isdigit, str(c.get("phone", ""))))
            if not c_phone: continue
            
            # Match exato ou match de sufixo (ignora 55 ou DDD se um dos lados não tiver)
            if target == c_phone or target.endswith(c_phone) or c_phone.endswith(target):
                return {"found": True, **c}
        return {"found": False}

    async def create_client(self, payload: Dict) -> Dict:
        res = await self._request("POST", "clients", data=payload)
        return res.get("client", res) if isinstance(res, dict) else res

    async def list_appointments(self, date: Optional[str] = None) -> Dict:
        params = {"date": date} if date else {}
        res = await self._request("GET", "appointments", params=params)
        return res if isinstance(res, dict) and "appointments" in res else {"appointments": res if isinstance(res, list) else []}

    async def create_appointment(self, payload: Dict) -> Dict:
        res = await self._request("POST", "appointments", data=payload)
        if isinstance(res, dict) and res.get("success"): return {"status": "success", **res}
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
