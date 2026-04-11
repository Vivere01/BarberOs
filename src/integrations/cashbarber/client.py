"""
BarberOS - CashBarber Scraper
===============================
Integração com o sistema CashBarber via web scraping.
Faz login com as credenciais do cliente e navega o painel admin.

NOTA: Esta é uma integração "pirata" — não usa API oficial.
O CashBarber não fornece API pública. Usamos o login
do cliente para acessar os dados do sistema.
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

logger = get_logger("integrations.cashbarber")


class CashBarberScraper(BaseScraper):
    """
    Scraper para o sistema CashBarber.

    Endpoints conhecidos (podem mudar — monitore nos logs):
    - POST /api/auth/login → Login
    - GET  /api/agenda/servicos → Serviços
    - GET  /api/agenda/profissionais → Profissionais
    - GET  /api/agenda/horarios-disponiveis → Horários
    - POST /api/agenda/agendar → Criar agendamento
    - POST /api/agenda/cancelar → Cancelar agendamento
    """

    SYSTEM_NAME = "cashbarber"

    async def login(self) -> None:
        """
        Faz login no CashBarber.

        O CashBarber usa autenticação por token JWT ou sessão.
        Tentamos ambos para compatibilidade.
        """
        client = await self._get_client()

        try:
            # Tenta login via API JSON
            response = await client.post(
                "/api/auth/login",
                json={
                    "email": self.username,
                    "password": self.password,
                },
            )

            if response.status_code == 200:
                data = response.json()
                self._session_token = data.get("token") or data.get("access_token", "")
                self._cookies = dict(response.cookies)
                self._session_created_at = datetime.utcnow()

                # Atualiza headers com token
                if self._session_token:
                    client.headers["Authorization"] = f"Bearer {self._session_token}"

                logger.info(
                    "CashBarber login successful",
                    barbershop_id=self.barbershop_id,
                )
                return

            # Tenta login via formulário (fallback)
            response = await client.post(
                "/login",
                data={
                    "email": self.username,
                    "senha": self.password,
                    "_token": await self._get_csrf_token(),
                },
            )

            if response.status_code in (200, 302):
                self._cookies = dict(response.cookies)
                self._session_token = self._cookies.get("session", "active")
                self._session_created_at = datetime.utcnow()
                logger.info("CashBarber login via form successful")
                return

            raise AuthenticationError(
                f"CashBarber login failed: {response.status_code}"
            )

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error("CashBarber login error", error=str(e))
            raise AuthenticationError(f"CashBarber login failed: {e}") from e

    async def _get_csrf_token(self) -> str:
        """Extrai CSRF token da página de login."""
        client = await self._get_client()
        try:
            response = await client.get("/login")
            soup = BeautifulSoup(response.text, "lxml")
            token_input = soup.find("input", {"name": "_token"})
            if token_input:
                return token_input.get("value", "")
        except Exception:
            pass
        return ""

    async def get_services(self) -> list[dict[str, Any]]:
        """Lista serviços cadastrados no CashBarber."""
        cache_key = f"services_{self.barbershop_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            response = await self._request("get", "/api/agenda/servicos")
            data = response.json()

            services = []
            items = data if isinstance(data, list) else data.get("data", data.get("servicos", []))

            for item in items:
                services.append({
                    "id": str(item.get("id", "")),
                    "name": item.get("nome", item.get("name", "")),
                    "price": item.get("preco", item.get("valor", item.get("price", ""))),
                    "duration": item.get("duracao", item.get("duration", "")),
                    "description": item.get("descricao", item.get("description", "")),
                    "active": item.get("ativo", item.get("active", True)),
                })

            # Filtra apenas ativos
            services = [s for s in services if s.get("active", True)]

            self._set_cached(cache_key, services)
            logger.info("Services loaded", count=len(services), system="cashbarber")
            return services

        except Exception as e:
            logger.error("Failed to load services", error=str(e), system="cashbarber")
            raise DataNotFoundError(f"Could not load services: {e}") from e

    async def get_professionals(self) -> list[dict[str, Any]]:
        """Lista profissionais cadastrados."""
        cache_key = f"professionals_{self.barbershop_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            response = await self._request("get", "/api/agenda/profissionais")
            data = response.json()

            professionals = []
            items = data if isinstance(data, list) else data.get("data", data.get("profissionais", []))

            for item in items:
                professionals.append({
                    "id": str(item.get("id", "")),
                    "name": item.get("nome", item.get("name", "")),
                    "active": item.get("ativo", item.get("active", True)),
                    "specialties": item.get("especialidades", []),
                })

            professionals = [p for p in professionals if p.get("active", True)]

            self._set_cached(cache_key, professionals)
            logger.info("Professionals loaded", count=len(professionals), system="cashbarber")
            return professionals

        except Exception as e:
            logger.error("Failed to load professionals", error=str(e), system="cashbarber")
            raise DataNotFoundError(f"Could not load professionals: {e}") from e

    async def get_available_slots(
        self,
        professional_id: str,
        date: str,
        service_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Busca horários disponíveis."""
        cache_key = f"slots_{self.barbershop_id}_{professional_id}_{date}_{service_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            params = {
                "profissional_id": professional_id,
                "data": date,
            }
            if service_id:
                params["servico_id"] = service_id

            response = await self._request(
                "get",
                "/api/agenda/horarios-disponiveis",
                params=params,
            )
            data = response.json()

            slots = []
            items = data if isinstance(data, list) else data.get("data", data.get("horarios", []))

            for item in items:
                if isinstance(item, str):
                    slots.append({"time": item, "available": True})
                else:
                    slots.append({
                        "time": item.get("horario", item.get("time", "")),
                        "available": item.get("disponivel", item.get("available", True)),
                    })

            # Filtra apenas disponíveis
            slots = [s for s in slots if s.get("available", True)]

            self._set_cached(cache_key, slots)
            logger.info(
                "Slots loaded",
                count=len(slots),
                professional=professional_id,
                date=date,
                system="cashbarber",
            )
            return slots

        except Exception as e:
            logger.error("Failed to load slots", error=str(e), system="cashbarber")
            raise DataNotFoundError(f"Could not load available slots: {e}") from e

    async def create_appointment(
        self,
        client_name: str,
        client_phone: str,
        service_id: str,
        professional_id: str,
        date: str,
        time: str,
    ) -> dict[str, Any]:
        """Cria agendamento no CashBarber."""
        try:
            response = await self._request(
                "post",
                "/api/agenda/agendar",
                json={
                    "cliente_nome": client_name,
                    "cliente_telefone": client_phone,
                    "servico_id": service_id,
                    "profissional_id": professional_id,
                    "data": date,
                    "horario": time,
                },
            )

            result = response.json()
            logger.info(
                "Appointment created",
                client=client_name,
                date=date,
                time=time,
                system="cashbarber",
            )

            # Invalida cache de slots
            self._cache = {k: v for k, v in self._cache.items() if "slots_" not in k}

            return {
                "success": True,
                "appointment_id": str(result.get("id", result.get("agendamento_id", ""))),
                "details": result,
            }

        except Exception as e:
            logger.error(
                "Failed to create appointment",
                error=str(e),
                system="cashbarber",
            )
            return {
                "success": False,
                "error": str(e),
            }

    async def cancel_appointment(self, appointment_id: str) -> dict[str, Any]:
        """Cancela agendamento no CashBarber."""
        try:
            response = await self._request(
                "post",
                "/api/agenda/cancelar",
                json={"agendamento_id": appointment_id},
            )
            logger.info("Appointment cancelled", id=appointment_id, system="cashbarber")
            return {"success": True, "details": response.json()}
        except Exception as e:
            logger.error("Cancel failed", error=str(e), system="cashbarber")
            return {"success": False, "error": str(e)}

    async def get_business_hours(self) -> dict[str, Any]:
        """Retorna horário de funcionamento."""
        cache_key = f"hours_{self.barbershop_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            response = await self._request("get", "/api/configuracoes/horarios")
            data = response.json()
            self._set_cached(cache_key, data)
            return data
        except Exception as e:
            logger.error("Failed to load hours", error=str(e), system="cashbarber")
            return {}
