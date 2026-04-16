import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class EvolutionApiClient:
    def __init__(self, base_url: str, api_key: str, instance_name: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.instance_name = instance_name
        self.headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }

    async def send_text(self, number: str, text: str) -> Dict[str, Any]:
        """Envia mensagem de texto via Evolution API."""
        # Limpa o número (remove @s.whatsapp.net se houver, o Evolution cuida disso ou espera o JID)
        url = f"{self.base_url}/message/sendText/{self.instance_name}"
        
        payload = {
            "number": number,
            "text": text,
            "linkPreview": True
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=self.headers, json=payload)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"Erro ao enviar mensagem via Evolution: {e}")
                return {"error": str(e)}
