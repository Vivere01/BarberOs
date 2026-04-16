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
        # Tenta o endpoint padrão e o alternativo
        endpoints = [
            f"{self.base_url}/message/sendText/{self.instance_name}",
            f"{self.base_url}/messages/sendText/{self.instance_name}",
            f"{self.base_url}/message/sendDirectText/{self.instance_name}"
        ]
        
        last_error = ""
        for url in endpoints:
            try:
                payload = {
                    "number": number.split("@")[0], # Remove @s.whatsapp.net se estiver lá para garantir compatibilidade
                    "text": text,
                    "linkPreview": False
                }
                headers = {"apikey": self.api_key, "Content-Type": "application/json"}
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json=payload, headers=headers)
                    if response.status_code in [200, 201]:
                        return response.json()
                    last_error = f"Status {response.status_code} em {url}"
            except Exception as e:
                last_error = str(e)
        
        print(f"EVOLUTION_SEND_ERROR: Falha após tentar múltiplos caminhos: {last_error}")
        return None
