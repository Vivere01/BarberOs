"""
BarberOS - Base Scraper
========================
Classe base para integração "pirata" com CashBarber e AppBarber.
Gerencia sessão, login, cookies e retry automático.

IMPORTANTE: Estas integrações não usam API oficial.
Elas fazem login com credenciais do cliente e navegam
o sistema como se fossem o usuário logado.
"""
from __future__ import annotations

import abc
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config.logging_config import get_logger

logger = get_logger("integrations.base")


class ScraperError(Exception):
    """Erro genérico do scraper."""
    pass


class AuthenticationError(ScraperError):
    """Erro de autenticação (login falhou)."""
    pass


class SessionExpiredError(ScraperError):
    """Sessão expirou, precisa relogar."""
    pass


class DataNotFoundError(ScraperError):
    """Dados não encontrados no sistema."""
    pass


class BaseScraper(abc.ABC):
    """
    Base para scrapers de sistemas de agendamento.

    Gerencia:
    - Login/autenticação com credenciais do cliente
    - Manutenção de sessão (cookies)
    - Retry automático com backoff exponencial
    - Cache de dados frequentes
    - Logging estruturado de todas as operações
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        barbershop_id: str,
        timeout: float = 30.0,
        session_ttl_minutes: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.barbershop_id = barbershop_id
        self.timeout = timeout
        self.session_ttl = timedelta(minutes=session_ttl_minutes)

        # Estado da sessão
        self._client: Optional[httpx.AsyncClient] = None
        self._session_token: Optional[str] = None
        self._session_created_at: Optional[datetime] = None
        self._cookies: dict[str, str] = {}

        # Cache simples
        self._cache: dict[str, Any] = {}
        self._cache_timestamps: dict[str, datetime] = {}
        self._cache_ttl = timedelta(minutes=5)

    async def ensure_session(self) -> None:
        """Garante que temos uma sessão válida."""
        if self._is_session_valid():
            return

        logger.info(
            "Session expired or not started, logging in",
            system=self.__class__.__name__,
            barbershop_id=self.barbershop_id,
        )
        await self.login()

    def _is_session_valid(self) -> bool:
        """Verifica se a sessão atual é válida."""
        if not self._session_token or not self._session_created_at:
            return False
        return datetime.utcnow() - self._session_created_at < self.session_ttl

    async def _get_client(self) -> httpx.AsyncClient:
        """Retorna ou cria o HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/html, */*",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
                cookies=self._cookies,
            )
        return self._client

    def _get_cached(self, key: str) -> Optional[Any]:
        """Retorna dados do cache se não expirado."""
        if key in self._cache:
            ts = self._cache_timestamps.get(key)
            if ts and datetime.utcnow() - ts < self._cache_ttl:
                logger.debug("Cache hit", key=key)
                return self._cache[key]
            else:
                del self._cache[key]
                if key in self._cache_timestamps:
                    del self._cache_timestamps[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        """Armazena dados no cache."""
        self._cache[key] = value
        self._cache_timestamps[key] = datetime.utcnow()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, SessionExpiredError)),
    )
    async def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        """Faz request com retry automático."""
        await self.ensure_session()
        client = await self._get_client()

        try:
            response = await getattr(client, method)(path, **kwargs)

            # Detecta sessão expirada (redirect para login)
            if response.status_code in (302, 401, 403):
                self._session_token = None
                raise SessionExpiredError(f"Session expired: {response.status_code}")

            response.raise_for_status()

            logger.debug(
                "Request successful",
                method=method.upper(),
                path=path,
                status=response.status_code,
                system=self.__class__.__name__,
            )

            return response

        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP error",
                method=method.upper(),
                path=path,
                status=e.response.status_code,
                system=self.__class__.__name__,
            )
            raise ScraperError(f"HTTP {e.response.status_code}: {path}") from e

    async def close(self) -> None:
        """Fecha o HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ─── Métodos abstratos que cada sistema implementa ───

    @abc.abstractmethod
    async def login(self) -> None:
        """Faz login no sistema. Implementação específica por sistema."""
        ...

    @abc.abstractmethod
    async def get_services(self) -> list[dict[str, Any]]:
        """Lista serviços disponíveis."""
        ...

    @abc.abstractmethod
    async def get_professionals(self) -> list[dict[str, Any]]:
        """Lista profissionais disponíveis."""
        ...

    @abc.abstractmethod
    async def get_available_slots(
        self,
        professional_id: str,
        date: str,
        service_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Lista horários disponíveis para um profissional em uma data."""
        ...

    @abc.abstractmethod
    async def create_appointment(
        self,
        client_name: str,
        client_phone: str,
        service_id: str,
        professional_id: str,
        date: str,
        time: str,
    ) -> dict[str, Any]:
        """Cria um agendamento no sistema."""
        ...

    @abc.abstractmethod
    async def cancel_appointment(
        self,
        appointment_id: str,
    ) -> dict[str, Any]:
        """Cancela um agendamento."""
        ...

    @abc.abstractmethod
    async def get_business_hours(self) -> dict[str, Any]:
        """Retorna horário de funcionamento."""
        ...
