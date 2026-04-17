"""
BarberOS - ChatBarber PRO API Client
=====================================
Client HTTP robusto para a API do ChatBarber PRO.
Inclui: connection pooling, timeout, retry com backoff e busca otimizada.
"""
import httpx
import logging
import asyncio
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Timeout global: connect=5s, read=15s, write=10s, pool=5s
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # segundos


class ChatBarberProClient:
    """
    Client para a API do ChatBarber PRO com:
    - Connection pooling (reutiliza conexões HTTP)
    - Timeout configurável (evita hanging indefinido)
    - Retry com exponential backoff (resiliência a erros transitórios)
    - Cache de clientes para busca rápida por telefone
    """
    
    # Connection pool compartilhado entre instâncias (mesmo base_url)
    _shared_clients: Dict[str, httpx.AsyncClient] = {}
    
    def __init__(self, api_token: str, owner_id: str, base_url: str = "https://www.chatbarber.pro"):
        self.api_token = api_token
        self.owner_id = owner_id
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
    
    def _get_pooled_client(self) -> httpx.AsyncClient:
        """Reutiliza client HTTP pela base_url (connection pooling)."""
        key = f"{self.base_url}:{self.api_token[:8]}"
        if key not in self._shared_clients or self._shared_clients[key].is_closed:
            self._shared_clients[key] = httpx.AsyncClient(
                timeout=_DEFAULT_TIMEOUT,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30.0
                ),
                follow_redirects=True
            )
        return self._shared_clients[key]

    async def _request_with_retry(self, method: str, endpoint: str, 
                                   data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Executa request HTTP com retry automático e backoff exponencial.
        
        Retry em: timeout, 5xx, connection errors.
        NÃO retry em: 4xx (erro do cliente — dados inválidos).
        """
        url = f"{self.base_url}/api/v1/{self.owner_id}/{endpoint}"
        client = self._get_pooled_client()
        last_error = None
        
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                if method == "GET":
                    response = await client.get(url, headers=self.headers)
                else:
                    response = await client.post(url, headers=self.headers, json=data)
                
                # 4xx = erro do cliente, não faz retry
                if 400 <= response.status_code < 500:
                    error_body = response.text[:500]
                    logger.error(f"CHATBARBERPRO_CLIENT_ERROR ({response.status_code}): {endpoint} -> {error_body}")
                    return {"error": f"HTTP {response.status_code}", "detail": error_body}
                
                response.raise_for_status()
                
                # Retorno vazio = sucesso sem body
                if not response.content:
                    return {"success": True}
                    
                return response.json()
                
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                last_error = e
                wait_time = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    f"CHATBARBERPRO_RETRY ({attempt}/{_MAX_RETRIES}): "
                    f"{endpoint} -> {type(e).__name__}: {str(e)[:100]}. "
                    f"Aguardando {wait_time:.1f}s..."
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(wait_time)
                    
            except httpx.HTTPStatusError as e:
                # 5xx = retry
                if e.response.status_code >= 500:
                    last_error = e
                    wait_time = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                    logger.warning(
                        f"CHATBARBERPRO_SERVER_ERROR ({attempt}/{_MAX_RETRIES}): "
                        f"{endpoint} -> {e.response.status_code}. Retry em {wait_time:.1f}s..."
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(wait_time)
                else:
                    logger.error(f"CHATBARBERPRO_HTTP_ERROR: {endpoint} -> {e.response.status_code}")
                    return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text[:500]}
                    
            except Exception as e:
                logger.error(f"CHATBARBERPRO_UNEXPECTED_ERROR: {endpoint} -> {type(e).__name__}: {str(e)[:200]}")
                return {"error": str(e)}
        
        # Esgotou tentativas
        error_msg = f"Falha após {_MAX_RETRIES} tentativas: {str(last_error)[:200]}"
        logger.error(f"CHATBARBERPRO_MAX_RETRIES: {endpoint} -> {error_msg}")
        return {"error": error_msg}

    # ===================================================================
    # API Methods
    # ===================================================================
    
    async def list_clients(self) -> Any:
        """Lista todos os clientes."""
        return await self._request_with_retry("GET", "clients")

    async def search_client_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        Busca cliente por telefone de forma otimizada.
        
        Tenta primeiro uma busca direta (se a API suportar query param).
        Se não, faz download de todos e filtra localmente com matching flexível.
        """
        phone_digits = ''.join(filter(str.isdigit, phone))
        
        # Tentativa 1: Busca direta por query param (se ChatBarber PRO suportar)
        try:
            result = await self._request_with_retry("GET", f"clients?phone={phone_digits}")
            if isinstance(result, dict) and not result.get("error"):
                clients = result.get("clients", []) if "clients" in result else (
                    [result] if result.get("id") else []
                )
                if clients:
                    c = clients[0]
                    return {"found": True, "id": c.get("id"), "name": c.get("name"), "phone": c.get("phone")}
        except Exception:
            pass  # Endpoint de busca não existe, fallback para lista completa
        
        # Tentativa 2: Lista completa + filtro local
        raw_data = await self._request_with_retry("GET", "clients")
        if isinstance(raw_data, dict) and raw_data.get("error"):
            return None
            
        clients_list = raw_data.get("clients", []) if isinstance(raw_data, dict) else (
            raw_data if isinstance(raw_data, list) else []
        )
        
        for client in clients_list:
            client_phone = ''.join(filter(str.isdigit, str(client.get("phone", ""))))
            # Matching flexível: últimos 8+ dígitos
            if len(phone_digits) > 8 and (phone_digits in client_phone or client_phone in phone_digits):
                return {"found": True, "id": client.get("id"), "name": client.get("name"), "phone": client.get("phone")}
            # Match exato
            if phone_digits == client_phone:
                return {"found": True, "id": client.get("id"), "name": client.get("name"), "phone": client.get("phone")}
        
        return {"found": False}

    async def create_client(self, name: str, phone: str, 
                            birth_date: Optional[str] = None,
                            email: Optional[str] = None, 
                            cpf: Optional[str] = None) -> Dict[str, Any]:
        """Cria novo cliente. Inclui data de nascimento (obrigatório no fluxo)."""
        data = {
            "name": name,
            "phone": phone,
        }
        # Só envia campos preenchidos para evitar rejeição da API
        if birth_date:
            data["birthDate"] = birth_date
        if email:
            data["email"] = email
        if cpf:
            data["cpf"] = cpf
        return await self._request_with_retry("POST", "clients", data)

    async def list_appointments(self) -> Any:
        """Lista todos os agendamentos."""
        return await self._request_with_retry("GET", "appointments")

    async def create_appointment(self, client_id: str, service_id: str, staff_id: str, 
                                  store_id: str, scheduled_at: str, 
                                  notes: str = "Agendamento via IA") -> Dict[str, Any]:
        """Cria agendamento."""
        data = {
            "clientId": client_id,
            "serviceId": service_id,
            "staffId": staff_id,
            "storeId": store_id,
            "scheduledAt": scheduled_at,
            "notes": notes
        }
        return await self._request_with_retry("POST", "appointments", data)

    async def list_services(self) -> Any:
        """Lista serviços disponíveis."""
        return await self._request_with_retry("GET", "services")

    async def list_staff(self) -> Any:
        """Lista profissionais/barbeiros."""
        return await self._request_with_retry("GET", "staff")

    async def get_ai_context(self) -> Dict[str, Any]:
        """Busca contexto de IA da barbearia (horários, regras, etc)."""
        return await self._request_with_retry("GET", "ai-context")
