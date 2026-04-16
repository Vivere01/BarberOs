import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ChatBarberProClient:
    def __init__(self, api_token: str, owner_id: str, base_url: str = "https://www.chatbarber.pro"):
        self.api_token = api_token
        self.owner_id = owner_id
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

    async def _get(self, endpoint: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/v1/{self.owner_id}/{endpoint}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Error calling {url}: {e}")
                raise

    async def _post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/api/v1/{self.owner_id}/{endpoint}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=self.headers, json=data)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Error calling {url}: {e}")
                raise

    # API Methods
    async def list_clients(self) -> List[Dict[str, Any]]:
        return await self._get("clients")

    async def create_client(self, name: str, phone: str, email: Optional[str] = None, cpf: Optional[str] = None) -> Dict[str, Any]:
        data = {
            "name": name,
            "phone": phone,
            "email": email,
            "cpf": cpf
        }
        return await self._post("clients", data)

    async def list_appointments(self) -> List[Dict[str, Any]]:
        return await self._get("appointments")

    async def create_appointment(self, client_id: str, service_id: str, staff_id: str, store_id: str, scheduled_at: str, notes: str = "Agendamento via IA") -> Dict[str, Any]:
        data = {
            "clientId": client_id,
            "serviceId": service_id,
            "staffId": staff_id,
            "storeId": store_id,
            "scheduledAt": scheduled_at,
            "notes": notes
        }
        return await self._post("appointments", data)

    async def list_services(self) -> List[Dict[str, Any]]:
        return await self._get("services")

    async def list_staff(self) -> List[Dict[str, Any]]:
        return await self._get("staff")

    async def get_ai_context(self) -> Dict[str, Any]:
        # Note: The provided endpoint was /api/v1/owner/ai-context (no owner_id in some examples, but I'll follow the pattern)
        return await self._get("ai-context")
