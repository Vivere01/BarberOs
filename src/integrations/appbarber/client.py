"""
BarberOS - AppBarber Scraper
==============================
Integração com o sistema AppBarber (StarApp Sistemas).
Similar ao CashBarber mas com endpoints e estrutura diferentes.

O AppBarber usa WebAdmin + App. Acessamos o WebAdmin.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from bs4 import BeautifulSoup

from src.integrations.base_scraper import (
    BaseScraper,
    AuthenticationError,
    DataNotFoundError,
)
from src.config.logging_config import get_logger

logger = get_logger("integrations.appbarber")


class AppBarberScraper(BaseScraper):
    """
    Scraper para o sistema AppBarber.

    Endpoints conhecidos:
    - POST /api/login → Login
    - GET  /api/servicos → Serviços
    - GET  /api/funcionarios → Profissionais
    - GET  /api/agenda/disponibilidade → Horários
    - POST /api/agenda/novo → Criar agendamento
    - DELETE /api/agenda/{id} → Cancelar agendamento
    """

    SYSTEM_NAME = "appbarber"

    async def login(self) -> None:
        """Faz login no AppBarber WebAdmin."""
        client = await self._get_client()

        try:
            # Login via API
            response = await client.post(
                "/api/login",
                json={
                    "login": self.username,
                    "senha": self.password,
                },
            )

            if response.status_code == 200:
                data = response.json()
                self._session_token = data.get("token", data.get("access_token", ""))
                self._cookies = dict(response.cookies)
                self._session_created_at = datetime.utcnow()

                if self._session_token:
                    client.headers["Authorization"] = f"Bearer {self._session_token}"

                logger.info(
                    "AppBarber login successful",
                    barbershop_id=self.barbershop_id,
                )
                return

            # Fallback: login via formulário web
            response = await client.post(
                "/admin/login",
                data={
                    "email": self.username,
                    "password": self.password,
                },
            )

            if response.status_code in (200, 302):
                self._cookies = dict(response.cookies)
                self._session_token = self._cookies.get("session", "active")
                self._session_created_at = datetime.utcnow()
                logger.info("AppBarber form login successful")
                return

            raise AuthenticationError(f"AppBarber login failed: {response.status_code}")

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error("AppBarber login error", error=str(e))
            raise AuthenticationError(f"AppBarber login failed: {e}") from e

    async def get_services(self) -> list[dict[str, Any]]:
        """Lista serviços do AppBarber."""
        cache_key = f"services_{self.barbershop_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            response = await self._request("get", "/api/servicos")
            data = response.json()

            services = []
            items = data if isinstance(data, list) else data.get("servicos", data.get("data", []))

            for item in items:
                services.append({
                    "id": str(item.get("id", "")),
                    "name": item.get("nome", item.get("descricao", "")),
                    "price": item.get("valor", item.get("preco", "")),
                    "duration": item.get("tempo", item.get("duracao", "")),
                    "description": item.get("observacao", ""),
                    "active": item.get("status", 1) == 1,
                })

            services = [s for s in services if s.get("active", True)]
            self._set_cached(cache_key, services)
            logger.info("Services loaded", count=len(services), system="appbarber")
            return services

        except Exception as e:
            logger.error("Failed to load services", error=str(e), system="appbarber")
            raise DataNotFoundError(f"Could not load services: {e}") from e

    async def get_professionals(self) -> list[dict[str, Any]]:
        """Lista profissionais do AppBarber."""
        cache_key = f"professionals_{self.barbershop_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            response = await self._request("get", "/api/funcionarios")
            data = response.json()

            professionals = []
            items = data if isinstance(data, list) else data.get("funcionarios", data.get("data", []))

            for item in items:
                professionals.append({
                    "id": str(item.get("id", "")),
                    "name": item.get("nome", ""),
                    "active": item.get("status", 1) == 1,
                    "specialties": item.get("servicos", []),
                })

            professionals = [p for p in professionals if p.get("active", True)]
            self._set_cached(cache_key, professionals)
            logger.info("Professionals loaded", count=len(professionals), system="appbarber")
            return professionals

        except Exception as e:
            logger.error("Failed to load professionals", error=str(e), system="appbarber")
            raise DataNotFoundError(f"Could not load professionals: {e}") from e

    async def get_available_slots(
        self,
        professional_id: str,
        date: str,
        service_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Busca horários disponíveis no AppBarber."""
        cache_key = f"slots_{self.barbershop_id}_{professional_id}_{date}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            params = {
                "funcionario_id": professional_id,
                "data": date,
            }
            if service_id:
                params["servico_id"] = service_id

            response = await self._request(
                "get",
                "/api/agenda/disponibilidade",
                params=params,
            )
            data = response.json()

            slots = []
            items = data if isinstance(data, list) else data.get("horarios", data.get("data", []))

            for item in items:
                if isinstance(item, str):
                    slots.append({"time": item, "available": True})
                else:
                    slots.append({
                        "time": item.get("hora", item.get("horario", "")),
                        "available": item.get("disponivel", True),
                    })

            slots = [s for s in slots if s.get("available", True)]
            self._set_cached(cache_key, slots)
            logger.info("Slots loaded", count=len(slots), system="appbarber")
            return slots

        except Exception as e:
            logger.error("Failed to load slots", error=str(e), system="appbarber")
            raise DataNotFoundError(f"Could not load slots: {e}") from e

    async def create_appointment(
        self,
        client_name: str,
        client_phone: str,
        service_id: str,
        professional_id: str,
        date: str,
        time: str,
    ) -> dict[str, Any]:
        """Cria agendamento no AppBarber."""
        try:
            response = await self._request(
                "post",
                "/api/agenda/novo",
                json={
                    "nome_cliente": client_name,
                    "telefone": client_phone,
                    "servico_id": service_id,
                    "funcionario_id": professional_id,
                    "data": date,
                    "hora": time,
                },
            )

            result = response.json()
            logger.info("Appointment created", system="appbarber")

            # Invalida cache
            self._cache = {k: v for k, v in self._cache.items() if "slots_" not in k}

            return {
                "success": True,
                "appointment_id": str(result.get("id", "")),
                "details": result,
            }

        except Exception as e:
            logger.error("Create appointment failed", error=str(e), system="appbarber")
            return {"success": False, "error": str(e)}

    async def cancel_appointment(self, appointment_id: str) -> dict[str, Any]:
        """Cancela agendamento no AppBarber."""
        try:
            response = await self._request(
                "delete",
                f"/api/agenda/{appointment_id}",
            )
            logger.info("Appointment cancelled", id=appointment_id, system="appbarber")
            return {"success": True}
        except Exception as e:
            logger.error("Cancel failed", error=str(e), system="appbarber")
            return {"success": False, "error": str(e)}

    async def get_business_hours(self) -> dict[str, Any]:
        """Retorna horário de funcionamento."""
        cache_key = f"hours_{self.barbershop_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            response = await self._request("get", "/api/configuracoes")
            data = response.json()
            hours = data.get("horario_funcionamento", data.get("horarios", {}))
            self._set_cached(cache_key, hours)
            return hours
        except Exception as e:
            logger.error("Failed to load hours", error=str(e), system="appbarber")
            return {}
