"""
BarberOS - UzAPI Client (WhatsApp Integration)
================================================
Cliente para a UzAPI que gerencia o envio e recebimento
de mensagens do WhatsApp.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from src.config.logging_config import get_logger
from src.config.settings import get_settings

logger = get_logger("integrations.uzapi")


class UzAPIClient:
    """
    Cliente HTTP para a UzAPI (WhatsApp).

    Gerencia:
    - Envio de mensagens de texto
    - Envio de mensagens com botões
    - Envio de listas interativas
    - Status de mensagens
    """

    def __init__(
        self,
        instance_id: str,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        settings = get_settings()
        self.instance_id = instance_id
        self.token = token or settings.uzapi_token
        self.base_url = (base_url or settings.uzapi_base_url).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                },
            )
        return self._client

    async def send_text(
        self,
        phone: str,
        message: str,
    ) -> dict[str, Any]:
        """Envia mensagem de texto simples."""
        client = await self._get_client()

        payload = {
            "phone": self._format_phone(phone),
            "message": message,
        }

        try:
            response = await client.post(
                f"/instance/{self.instance_id}/message/text",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

            logger.info(
                "WhatsApp text sent",
                phone=phone[:8] + "****",
                message_length=len(message),
            )
            return result

        except Exception as e:
            logger.error("Failed to send WhatsApp text", error=str(e), phone=phone[:8] + "****")
            raise

    async def send_buttons(
        self,
        phone: str,
        message: str,
        buttons: list[dict[str, str]],
        title: str = "",
        footer: str = "",
    ) -> dict[str, Any]:
        """Envia mensagem com botões interativos."""
        client = await self._get_client()

        payload = {
            "phone": self._format_phone(phone),
            "title": title,
            "message": message,
            "footer": footer,
            "buttons": buttons,
        }

        try:
            response = await client.post(
                f"/instance/{self.instance_id}/message/buttons",
                json=payload,
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error("Failed to send buttons", error=str(e))
            # Fallback: envia como texto
            return await self.send_text(phone, message)

    async def send_list(
        self,
        phone: str,
        message: str,
        sections: list[dict[str, Any]],
        title: str = "",
        button_text: str = "Ver opções",
        footer: str = "",
    ) -> dict[str, Any]:
        """Envia mensagem com lista interativa."""
        client = await self._get_client()

        payload = {
            "phone": self._format_phone(phone),
            "title": title,
            "message": message,
            "footer": footer,
            "buttonText": button_text,
            "sections": sections,
        }

        try:
            response = await client.post(
                f"/instance/{self.instance_id}/message/list",
                json=payload,
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error("Failed to send list", error=str(e))
            return await self.send_text(phone, message)

    def _format_phone(self, phone: str) -> str:
        """Formata telefone para padrão WhatsApp (55XXXXXXXXXXX)."""
        phone = "".join(c for c in phone if c.isdigit())
        if not phone.startswith("55"):
            phone = "55" + phone
        return phone

    async def close(self) -> None:
        """Fecha o HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
